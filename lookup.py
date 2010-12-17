#!/usr/bin/env python
#
# lookup.py
# 

import base64
import hashlib
import hmac
import locale
import os
import platform
import sys
import time
import urllib
import urllib2

import gflags as flags
import google.apputils.app as app
import google.apputils.appcommands as appcommands

# URL encoding process is described here:
#   http://docs.amazonwebservices.com/AWSECommerceService/latest/DG/
AMAZON_ROOT_URL = 'http://webservices.amazon.com/onca/xml'
AMAZON_PREAMBLE = """GET
webservices.amazon.com
/onca/xml
"""

_FORMAT = '%s.txt' if platform.system() == 'Windows' else '.%s'


FLAGS = flags.FLAGS
flags.DEFINE_string('amazon_id_file',
                    os.path.join(os.path.expanduser('~'),
                                 _FORMAT % ('amazon-id',)),
                    'File containing amazon identity')
flags.DEFINE_string('amazon_key_file',
                    os.path.join(os.path.expanduser('~'),
                                 _FORMAT % ('amazon-key',)),
                    'File containing amazon secret key')

locale.setlocale(locale.LC_ALL, '')


def _FileToString(filename):
    """Given a file, return a string containing the contents."""
    if not os.path.exists(filename):
        return ""
    lines = open(filename, 'r').readlines()
    return ''.join([x.strip() for x in lines])


def _PrintSalesRank(sales_rank):
    try:
        rank = int(sales_rank)
        print "Sales Rank: " + locale.format("%d", rank, grouping=True)
    except ValueError:
        print "Sales Rank: %s" % (sales_rank,)


def _PrintBestPrice(best_price):
    try:
        price = float(best_price)
        print "Best Price: $%s" % (best_price,)
    except ValueError:
        print "Best Price: %s" % (best_price,)

def _EncodeUrl(isbn):
    parameters = {
        'AWSAccessKeyId': _FileToString(FLAGS.amazon_id_file),
        'ItemId': isbn,
        'Operation': 'ItemLookup',
        'ResponseGroup': 'SalesRank,OfferSummary',
        'Service': 'AWSECommerceService',
        'Timestamp': time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        'Version': '2010-09-01',
        }
    query_string = '&'.join(sorted(urllib.urlencode(parameters).split('&')))
    string_to_sign = AMAZON_PREAMBLE + query_string

    encoding_key = _FileToString(FLAGS.amazon_key_file)
    encoder = hmac.new(encoding_key, digestmod=hashlib.sha256)
    encoder.update(string_to_sign)
    signature = base64.b64encode(encoder.digest())
    parameters['Signature'] = signature

    final_url = AMAZON_ROOT_URL + '?' + urllib.urlencode(parameters)
    return final_url

def _LookupIsbn(isbn):
    lookup_url = _EncodeUrl(isbn)
    try:
        response = urllib2.urlopen(lookup_url)
    except URLError, e:
        print "Error looking up ISBN."
        print "URL: %s" % lookup_url
        print "Response: %s" % str(e)
        exit(1)
    if response.getcode() != 200:
        print "Error looking up ISBN. Error code: %s" % response.getcode()
        exit(1)
    xml_response = response.readline()
    # What I should really do is create a parser, parse the response,
    # do something with relevant data, maybe do verification/sanity
    # checks, etc. Instead, just grab the things I know are there.

    # sales rank HACK
    sales_rank = '(None)'
    if '<SalesRank>' in xml_response:
        sales_rank = xml_response.partition('<SalesRank>')[2].partition(
            '</SalesRank>')[0]

    # lowest price HACK
    if '<Amount>' in xml_response:
        prices = []
        for s in xml_response.split('<Amount>')[1:]:
            prices.append(s[:s.find('<')])
        best_price = "%.2f" % (min([int(p) for p in prices])/100.0,)
    else:
        best_price = '(None)'

    return best_price, sales_rank

class EncodeUrlCmd(appcommands.Cmd):
    """Given an ISBN, encode a URL that looks up that ISBN."""
    def Run(self, argv):
        if len(argv) != 2:
            app.usage(shorthelp=1,
                      detailed_error='Incorrect number of arguments, ' +
                      'expected 1, got %s' % (len(argv) - 1,),
                      exitcode=1)

        isbn = str(argv[1])
        print _EncodeUrl(isbn)


class LookupIsbnCmd(appcommands.Cmd):
    """Given an ISBN, look it up and print the lowest price and sales rank."""
    def Run(self, argv):
        if len(argv) != 2:
            app.usage(shorthelp=1,
                      detailed_error='Incorrect number of arguments, ' +
                      'expected 1, got %s' % (len(argv) - 1,),
                      exitcode=1)

        isbn = str(argv[1])
        best_price, sales_rank = _LookupIsbn(isbn)
        print "ISBN: %s" % (isbn,)
        _PrintBestPrice(best_price)
        _PrintSalesRank(sales_rank)


class LookupAllCmd(appcommands.Cmd):
    """Given a filename, look up all ISBNs in that file."""
    def __init__(self, argv, fv):
        super(LookupAllCmd, self).__init__(argv, fv)
        flags.DEFINE_boolean('price_only', False,
                             'Only print price information, not sales rank.')
        flags.DEFINE_boolean('quiet', False,
                             'Only output to file.')
        flags.DEFINE_string('output_filename', None,
                            'Filename to output results of ISBN lookups.')
        
    def Run(self, argv):
        if len(argv) != 2:
            app.usage(shorthelp=1,
                      detailed_error='Incorrect number of arguments, ' +
                      'expected 1, got %s' % (len(argv) - 1,),
                      exitcode=1)
        if FLAGS.quiet and FLAGS.output_filename is None:
            app.usage(shorthelp=1,
                      detailed_error='Quiet and no output file -- nothing to do!',
                      exitcode=1)
        input_file = argv[1]
        if not os.path.exists(input_file):
            print "Cannot find file: %s" % (input_file,)
            exit(1)
        if FLAGS.output_filename:
            f = open(FLAGS.output_filename, 'w')

        if not FLAGS.quiet:
            format = "%13s %10s %12s"
            print "    ISBN         Price    Sales Rank "
            print "------------- ---------- ------------"
            
        isbn_ls = [x.rstrip() for x in open(input_file, 'r').readlines()]
        for isbn in isbn_ls:
            best_price, sales_rank = _LookupIsbn(isbn)
            
            # output to file
            if FLAGS.output_filename:
                if FLAGS.price_only:
                    print >>f, "%s %s"%(isbn, best_price)
                else:
                    print >>f, "%s %s %s"%(isbn, best_price, sales_rank)
                    
            # print to terminal
            if not FLAGS.quiet:
                try:
                    price = "$%.2f" % (float(best_price),)
                except ValueError:
                    price = "(None)"
                try:
                    rank = locale.format("%d", int(sales_rank),
                                         grouping=True)
                except ValueError:
                    rank = "(None)"
                print format % (isbn, price, rank)
        if FLAGS.output_filename:
            f.close()
            
            
def main(argv):
    appcommands.AddCmd('encode', EncodeUrlCmd)
    appcommands.AddCmd('lookup', LookupIsbnCmd)
    appcommands.AddCmd('batch', LookupAllCmd)

    
# pylint: disable-msg=C6409
def run_main():
    """Function to be used as setuptools script entry point.

    Appcommands assumes that it always runs as __main__, but launching
    via a setuptools-generated entry_point breaks this rule. We do some
    trickery here to make sure that appcommands and flags find their
    state where they expect to by faking ourselves as __main__.
    """
    # Put the flags for this module somewhere the flags module will look
    # for them.
    new_name = flags._GetMainModule()
    sys.modules[new_name] = sys.modules['__main__']
    for flag in FLAGS.FlagsByModuleDict().get(__name__, []):
        FLAGS._RegisterFlagByModule(new_name, flag)
    for key_flag in FLAGS.KeyFlagsByModuleDict().get(__name__, []):
        FLAGS._RegisterKeyFlagForModule(new_name, key_flag)
    # Now set __main__ appropriately so that appcommands will be
    # happy.
    sys.modules['__main__'] = sys.modules[__name__]
    appcommands.Run()
    sys.modules['__main__'] = sys.modules.pop(new_name)

                                        
if __name__ == '__main__':
    appcommands.Run()
