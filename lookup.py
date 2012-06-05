#!/usr/bin/env python
#
# lookup.py
# 

import base64
import csv
import hashlib
import hmac
import locale
import os
import platform
import pprint
import re
import sys
import time
import urllib
import urllib2
import xml
import xml.etree.ElementTree as ElementTree


import gflags as flags
import google.apputils.app as app
import google.apputils.appcommands as appcommands

# URL encoding process is described here:
#   http://docs.amazonwebservices.com/AWSECommerceService/latest/DG/
_FORMAT = '%s.txt' if platform.system() == 'Windows' else '.%s'
locale.setlocale(locale.LC_ALL, '')
FLAGS = flags.FLAGS


flags.DEFINE_string(
  'amazon_associate_id_file',
  os.path.join(os.path.expanduser('~'), _FORMAT % ('amazon-associate-id',)),
  'File containing amazon associate ID')
flags.DEFINE_string(
  'amazon_id_file',
  os.path.join(os.path.expanduser('~'), _FORMAT % ('amazon-id',)),
  'File containing amazon identity')
flags.DEFINE_string(
  'amazon_key_file',
  os.path.join(os.path.expanduser('~'), _FORMAT % ('amazon-key',)),
  'File containing amazon secret key')

_CLIENT = None
def Client():
  global _CLIENT
  if _CLIENT is None:
    _CLIENT = AmazonClient()
  return _CLIENT


def _PrintXml(xml):
  import xml.dom.minidom as minidom
  print minidom.parseString(xml).toprettyxml()


class MaybeSalesRank(object):
  def __init__(self, rank=None):
    if rank is not None:
      self.rank = int(rank)
    else:
      self.rank = None

  @property
  def defined(self):
    return self.rank is not None

  def __str__(self):
    if self.defined:
      return str(self.rank)
    else:
      return '(None)'
  
  def __repr__(self):
    if self.defined:
      return locale.format('%d', self.rank, grouping=True)
    else:
      return '(None)'


class MaybePrice(object):
  def __init__(self, value=None):
    self.price = None
    if isinstance(value, int):
      self.price = value
    elif isinstance(value, float):
      self.price = int(100 * value)
    elif isinstance(value, basestring):
      self.price = int(float(value))

  @property
  def defined(self):
    return self.price is not None
      
  def __str__(self):
    if self.defined:
      return '$%.2f' % (self.price / 100.0,)
    else:
      return '(None)'

  def __repr__(self):
    return str(self)

  def __cmp__(self, other):
    if not isinstance(other, MaybePrice):
      raise ValueError('cannot compare MaybePrice to %s' % (type(other).__name__,))
    elif not self.defined:
      return 1
    elif not other.defined:
      return -1
    else:
      return cmp(self.price, other.price)


class Isbn(object):
  def __init__(self, raw_isbn):
    self.isbn = Isbn.Normalize(raw_isbn)

  def __str__(self):
    return '%s' % (self.isbn,)

  def __repr__(self):
    return 'ISBN: %s' % (self,)

  def __cmp__(self, other):
    if not isinstance(other, Isbn):
      raise ValueError('cannot compare Isbn to %s' % (type(other).__name__,))
    return cmp(self.isbn, other.isbn)

  @staticmethod
  def _CalculateCheckDigit(digits):
    def _DotProduct(xs, ys):
      return sum(int(x)*int(y) for x, y in zip(xs, ys))

    if len(digits) == 9:
      digit_sum = _DotProduct(digits, range(1,10)) % 11
      if digit_sum != 10:
        return str(digit_sum)
      else:
        return 'X'
    elif len(digits) == 12:
      digit_sum = 10 - _DotProduct(digits, [1, 3] * 6) % 10
      return str(10 - digit_sum)
    else:
      raise ValueError('invalid ISBN length: %s' % len(digits))

  @staticmethod
  def Normalize(raw_isbn):
    isbn = ''.join(x for x in raw_isbn if x.isdigit())
    if not isbn:
      raise ValueError('Invalid ISBN: %s' % (raw_isbn,))
    if raw_isbn.rstrip()[-1].upper() == 'X':
      isbn += 'X'

    # Having calculated the provided ISBN, we now deal with corner
    # cases and remove the last digit (which we simply recalculate).
    if len(isbn) == 9:  # old British ISBNs
      root = '0' + isbn[:-1]
    elif len(isbn) == 10:
      root = isbn[:-1]
    elif len(isbn) == 13:
      root = isbn[3:-1]
    else:
      raise ValueError('Invalid ISBN (wrong length): %s' % (raw_isbn,))

    checksum = Isbn._CalculateCheckDigit(root)
    return root + checksum
    
class AmazonClient(object):
  AMAZON_ROOT_URL = 'http://webservices.amazon.com/onca/xml'
  AMAZON_PREAMBLE = """GET\nwebservices.amazon.com\n/onca/xml\n"""

  def __init__(self, **kwds):
    ReadFile = lambda f: open(f).read().strip()
    self.amazon_id = ReadFile(FLAGS.amazon_id_file)
    self.amazon_key = ReadFile(FLAGS.amazon_key_file)
    self.amazon_associate_id = ReadFile(FLAGS.amazon_associate_id_file)

  def EncodeUrl(self, isbns):
    response_groups = 'SalesRank,Offers,ItemAttributes'
    parameters = {
      'AssociateTag': self.amazon_associate_id,
      'AWSAccessKeyId': self.amazon_id,
      'ItemId': ','.join(str(isbn) for isbn in isbns),
      'Operation': 'ItemLookup',
      'ResponseGroup': response_groups,
      'Service': 'AWSECommerceService',
      'Timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
      'Version': '2010-09-01',
      }
    query_string = '&'.join(sorted(urllib.urlencode(parameters).split('&')))
    string_to_sign = AmazonClient.AMAZON_PREAMBLE + query_string

    encoding_key = self.amazon_key
    encoder = hmac.new(encoding_key, digestmod=hashlib.sha256)
    encoder.update(string_to_sign)
    signature = base64.b64encode(encoder.digest())
    parameters['Signature'] = signature

    final_url = AmazonClient.AMAZON_ROOT_URL + '?' + urllib.urlencode(parameters)
    return final_url

  def LookupIsbns(self, isbns):
    if len(isbns) > 10:
      raise RuntimeError('Cannot look up more than 10 ISBNs per request.')
    lookup_url = self.EncodeUrl(isbns)
    try:
      response = urllib2.urlopen(lookup_url)
    except urllib2.URLError, e:
      raise RuntimeError('Error looking up ISBN.\nURL: %s\nResponse: %s\n' %
        (lookup_url, str(e)))
    if response.getcode() != 200:
      raise RuntimeError('Error looking up ISBN. Error code: ' +
        `response.getcode()`)
    return response.readline()

  @staticmethod
  def GetSalesInfo(xml_response):
    def _FindChildren(xml, tag):
      namespace = re.finditer('{(.*)}.*', xml.tag).next().groups()[0]
      resolved_tags = ['{%s}%s' % (namespace, tag) for tag in tag.split('/')]
      result = xml.findall('.//' + '/'.join(resolved_tags))
      return result

    def _FindChild(xml, tag, default=None):
      results = _FindChildren(xml, tag)
      if results:
        return results[0].text
      else:
        return default

    xml = ElementTree.XML(xml_response)
    # Check for a failed request
    errors = _FindChildren(xml, 'Errors')
    if errors:
      raise ValueError(_FindChild(errors[0], 'Message', '(Unknown error)'))

    results = {}
    for item in _FindChildren(xml, 'Item'):
      item_info = {}
      item_info['sales_rank'] = MaybeSalesRank(
        _FindChild(item, 'SalesRank', default='(None)'))
      offer_summary = _FindChildren(item, 'OfferSummary')[0]
      item_info['best_used_price'] = MaybePrice(
        _FindChild(offer_summary, 'LowestUsedPrice/Amount'))
      item_info['best_new_price'] = MaybePrice(
        _FindChild(offer_summary, 'LowestNewPrice/Amount'))
      item_info['best_price'] = min(item_info['best_new_price'],
        item_info['best_used_price'])
      item_info['amazon_price'] = MaybePrice(
        _FindChild(item, 'OfferListing/Price/Amount'))
      item_info['title'] = _FindChild(item, 'Title')
      item_info['isbn'] = _FindChild(item, 'ASIN')
      item_info['timestamp'] = (int(time.time()) // 1000) * 1000
      results[item_info['isbn']] = item_info

    return results


class EncodeUrlCmd(appcommands.Cmd):
  """Given an ISBN, encode a URL that looks up that ISBN."""
  def Run(self, argv):
    if len(argv) != 2:
      app.usage(shorthelp=1,
        detailed_error='Incorrect number of arguments, ' +
        'expected 1, got %s' % (len(argv) - 1,),
        exitcode=1)

    isbn = Isbn(argv[1])
    print Client().EncodeUrl([isbn])


class LookupIsbnCmd(appcommands.Cmd):
  """Given an ISBN, look it up and print the lowest price and sales rank."""
  def Run(self, argv):
    if len(argv) != 2:
      app.usage(shorthelp=1,
        detailed_error='Incorrect number of arguments, ' +
        'expected 1, got %s' % (len(argv) - 1,),
        exitcode=1)

    isbn = Isbn(argv[1])
    try:
      response = Client().LookupIsbns([isbn])
      item_info = AmazonClient.GetSalesInfo(response)[str(isbn)]
    except RuntimeError, e:
      print "Error looking up ISBN:",
      if '\n' in e:
        print
      print e
      exit(1)
    print 'ISBN: %s' % (item_info['isbn'],)
    print 'Best Price: %s' % (item_info['best_price'],)
    print 'Amazon Price: %s' % (item_info['amazon_price'],)
    print 'Sales Rank: %r' % (item_info['sales_rank'],)
    print 'Title: %s' % (item_info['title'],)


class LookupAllCmd(appcommands.Cmd):
  """Given a filename, look up all ISBNs in that file."""
  def __init__(self, argv, fv):
    super(LookupAllCmd, self).__init__(argv, fv)
    flags.DEFINE_boolean('full_info', False,
      'Print all information to file, not just isbn and sales rank.')
    flags.DEFINE_boolean('abbreviate', True,
      'Abbreviate titles to fit on one line.')
    flags.DEFINE_boolean('quiet', False,
      'Only output to file.')
    self.outfile = None
    self.csv_writer = None

  def __del__(self):
    if self.outfile is not None:
      self.outfile.close()

  def PrintItem(self, isbn, item_info=None):
    if item_info is None:
      best_price = MaybePrice()
      sales_rank = MaybeSalesRank()
      title = ''
    else:
      best_price = item_info['best_price']
      sales_rank = item_info['sales_rank']
      title = item_info['title']

    # output to file
    if self.outfile is not None:
      if FLAGS.full_info:
        print >>self.outfile, '%s %s %s %s' % (
          isbn, best_price, sales_rank, title)
      else:
        print >>self.outfile, '%s %s' % (
          isbn, best_price)

    # print to terminal
    if not FLAGS.quiet:
      fmt = '%13s %9s  %11r   %s'
      if FLAGS.abbreviate and len(title) > 45:
        title = title[:42] + '...'
      print fmt % (isbn, best_price, sales_rank, title)


  def WriteCsv(self, results, write_header=False):
    if self.csv_writer is None:
      self.csv_writer = csv.DictWriter(
        self.outfile, 
        ['timestamp', 'isbn', 'amazon_price', 'best_new_price',
         'best_used_price', 'sales_rank', 'title'],
        extrasaction='ignore',
        lineterminator='\n',
        quoting=csv.QUOTE_MINIMAL)
      if write_header:
        self.csv_writer.writeheader()
    self.csv_writer.writerows(results.itervalues())
    
  def Run(self, argv):
    if len(argv) not in [2, 3]:
      app.usage(shorthelp=1,
        detailed_error='Incorrect number of arguments, ' +
        'expected 1 or 2, got %s' % (len(argv) - 1,),
        exitcode=1)

    if len(argv) == 3:
      if FLAGS.quiet and output_filename is None:
        print 'Quiet and no output file -- nothing to do!'
        return
      outfile_name = argv[2]
      as_csv = outfile_name.endswith('.csv')
      new_outfile = not os.path.exists(outfile_name)
      self.outfile = open(outfile_name, 'a')

    input_file = argv[1]
    if not os.path.exists(input_file):
      print 'Cannot find file: %s' % (input_file,)
      exit(1)
    
    if not (FLAGS.quiet or as_csv):
      print '    ISBN         Price    Sales Rank              Title'
      print '------------- ---------- ------------',
      print '-----------------------------------------------'

    isbn_ls = map(Isbn, open(input_file).readlines())
    while isbn_ls:
      batch = map(str, isbn_ls[:10])
      isbn_ls = isbn_ls[len(batch):]
      response = Client().LookupIsbns(batch)
      sales_infos = AmazonClient.GetSalesInfo(response)
      if as_csv:
        self.WriteCsv(sales_infos, write_header=new_outfile)
      else:
        for isbn in batch:
          self.PrintItem(isbn, sales_infos.get(isbn))


class ValidateIsbnCmd(appcommands.Cmd):
  """Validate an ISBN."""
  def Run(self, argv):
    if len(argv) != 2:
      app.usage(shorthelp=1,
        detailed_error='Incorrect number of arguments, ' +
        'expected 1, got %s' % (len(argv) - 1,),
        exitcode=1)
    isbn = Isbn(argv[1])
    print isbn


class VerifyCmd(appcommands.Cmd):
  """Verify that we can find the amazon key and secret, and that
  they're valid."""
  def Run(self, argv):
    print 'Checking for amazon id file ...',
    sys.stdout.flush()
    if not os.path.exists(FLAGS.amazon_id_file):
      print 'FAIL'
      print 'Cannot find amazon id file:', FLAGS.amazon_id_file
      exit(1)
    print 'DONE'
    print 'Checking for amazon secret key file ...',
    sys.stdout.flush()
    if not os.path.exists(FLAGS.amazon_key_file):
      print 'FAIL'
      print 'Cannot find amazon secret key file:', FLAGS.amazon_key_file
      exit(1)
    print 'DONE'
    print 'Trying ISBN lookup ...',
    sys.stdout.flush()
    try:
      Client().LookupIsbns(['1573980137'])
    except RuntimeError, e:
      print 'FAIL'
      print 'Error trying to lookup a valid ISBN:',
      if '\n' in e:
        print
      print e
      exit(1)
    print 'DONE'
    print 'Verification complete! Everything seems in order.'

    
def main(argv):
  appcommands.AddCmd('batch', LookupAllCmd)
  appcommands.AddCmd('encode', EncodeUrlCmd)
  appcommands.AddCmd('lookup', LookupIsbnCmd)
  appcommands.AddCmd('validate_isbn', ValidateIsbnCmd)
  appcommands.AddCmd('verify', VerifyCmd)


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
