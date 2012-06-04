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
import xml.dom.minidom as minidom
import xml.etree.ElementTree as ElementTree


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

locale.setlocale(locale.LC_ALL, '')


def _FileToString(filename):
  """Given a file, return a string containing the contents."""
  if not os.path.exists(filename):
    return ''
  lines = open(filename, 'r').readlines()
  return ''.join([x.strip() for x in lines])


def _PrintSalesRank(sales_rank):
  try:
    rank = int(sales_rank)
    print 'Sales Rank: ' + locale.format('%d', rank, grouping=True)
  except ValueError:
    print 'Sales Rank: %s' % (sales_rank,)


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

    
def _PrintTitle(title):
  if title:
    print 'Title: %s' % (title,)


def _DotProduct(xs, ys):
  return sum(int(x)*int(y) for x, y in zip(xs, ys))


def _OnlyDigitsX(s):
  result = ''
  for x in s:
    if x.isdigit():
      result += x
  if (s and s[-1].upper() == 'X'):
    result += s[-1]
  return result


def _IsbnCheckDigit(digits):
  if len(digits) == 9:
    sum = _DotProduct(digits, range(1,10)) % 11
    if sum != 10:
      return str(sum)
    else:
      return 'X'
  elif len(digits) == 12:
    sum = 10 - _DotProduct(digits, [1, 3] * 6) % 10
    return str(10 - sum)
  else:
    raise ValueError('invalid ISBN length: %s' % len(digits))


def _GetSalesInfo(xml_response):
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
    item_info['sales_rank'] = _FindChild(
      item, 'SalesRank', default='(None)')
    offer_summary = _FindChildren(item, 'OfferSummary')[0]
    item_info['best_used_price'] = MaybePrice(
      _FindChild(offer_summary, 'LowestUsedPrice/Amount', None))
    item_info['best_new_price'] = MaybePrice(
      _FindChild(offer_summary, 'LowestNewPrice/Amount', None))
    item_info['best_price'] = min(item_info['best_new_price'],
                                  item_info['best_used_price'])
    item_info['title'] = _FindChild(item, 'Title')
    item_info['isbn'] = _FindChild(item, 'ASIN')
    results[item_info['isbn']] = item_info

  #pprint.pprint(results)
    
  return results

  
def _CompareIsbns(x, y):
  return x.lower() == y.lower()


def _NormalizeIsbn(isbn):
  # Get rid of extra characters
  isbn = _OnlyDigitsX(isbn)
  # Handle old British ISBNs:
  if len(isbn) == 9:
    root = '0' + isbn[-1]
  elif len(isbn) == 10:
    root = isbn[:-1]
  # Move ISBN13 to ISBN10
  elif len(isbn) == 13:
    root = isbn[3:-1]
  else:
    raise RuntimeError('Invalid ISBN (wrong length): %s' % (isbn,))

  checksum = _IsbnCheckDigit(root)
  return (root + checksum, not _CompareIsbns(root + checksum, isbn))


def _EncodeUrl(isbn, get_title=False):
  response_groups = 'SalesRank,OfferSummary'
  if get_title:
    response_groups += ',ItemAttributes'
  parameters = {
    'AssociateTag': _FileToString(FLAGS.amazon_associate_id_file),
    'AWSAccessKeyId': _FileToString(FLAGS.amazon_id_file),
    'ItemId': isbn,
    'Operation': 'ItemLookup',
    'ResponseGroup': response_groups,
    'Service': 'AWSECommerceService',
    'Timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
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
  isbn, _ = _NormalizeIsbn(isbn)
  lookup_url = _EncodeUrl(isbn, get_title=True)
  try:
    response = urllib2.urlopen(lookup_url)
  except urllib2.URLError, e:
    raise RuntimeError('Error looking up ISBN.\nURL: %s\nResponse: %s\n' %
      (lookup_url, str(e)))
  if response.getcode() != 200:
    raise RuntimeError('Error looking up ISBN. Error code: ' +
      `response.getcode()`)
  return response.readline()


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

    isbn, _ = _NormalizeIsbn(str(argv[1]))
    try:
      response = _LookupIsbn(isbn)
      item_info = _GetSalesInfo(response)[isbn]
    except RuntimeError, e:
      print "Error looking up ISBN:",
      if '\n' in e:
        print
      print e
      exit(1)
    print 'ISBN: %s' % (item_info['isbn'],)
    print 'Best Price: %s' % (item_info['best_price'],)
    _PrintSalesRank(item_info['sales_rank'])
    _PrintTitle(item_info['title'])


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

  def Run(self, argv):
    if len(argv) not in [2, 3]:
      app.usage(shorthelp=1,
        detailed_error='Incorrect number of arguments, ' +
        'expected 1 or 2, got %s' % (len(argv) - 1,),
        exitcode=1)

    output_filename = argv[2] if len(argv) == 3 else None
    if FLAGS.quiet and output_filename is None:
      print 'Quiet and no output file -- nothing to do!'
      return

    input_file = argv[1]
    if not os.path.exists(input_file):
      print 'Cannot find file: %s' % (input_file,)
      exit(1)
    if output_filename is not None:
      f = open(output_filename, 'w')
    
    if not FLAGS.quiet:
      format = '%13s %9s  %11s   %s'
      print '    ISBN         Price    Sales Rank              Title'
      print '------------- ---------- ------------',
      print '-----------------------------------------------'

    isbn_ls = [_OnlyDigitsX(x.rstrip()) for x in open(input_file, 'r').readlines()]
    for orig_isbn in isbn_ls:
      isbn, _ = _NormalizeIsbn(orig_isbn)
      try:
        response = _LookupIsbn(isbn)
        item_info = _GetSalesInfo(response)[isbn]
        best_price = item_info['best_price']
        sales_rank = item_info['sales_rank']
        title = item_info['title']
      except RuntimeError, e:
        best_price = MaybePrice()
        sales_rank = ''
        title = ''

      # output to file
      if output_filename:
        if FLAGS.full_info:
          print >>f, '%s %s %s %s'%(isbn, best_price, sales_rank,
            title)
        else:
          print >>f, '%s %s'%(_NormalizeIsbn(isbn)[0], best_price)

      # print to terminal
      if not FLAGS.quiet:
        try:
          rank = locale.format('%d', int(sales_rank),
            grouping=True)
        except ValueError:
          rank = '(None)'
        if FLAGS.abbreviate and len(title) > 45:
          title = title[:42] + '...'
        print format % (isbn, best_price, rank, title)
    if output_filename is not None:
      f.close()


class ValidateIsbnCmd(appcommands.Cmd):
  """Validate an ISBN."""
  def Run(self, argv):
    if len(argv) != 2:
      app.usage(shorthelp=1,
        detailed_error='Incorrect number of arguments, ' +
        'expected 1, got %s' % (len(argv) - 1,),
        exitcode=1)
    isbn = _OnlyDigitsX(argv[1])
    print 'ISBN: %s' % (isbn,)
    checksum = _IsbnCheckDigit(isbn[:-1])
    if (checksum != isbn[-1]):
      print 'Corrected ISBN: %s' % (isbn[:-1] + checksum)
    if len(isbn) != 10:
      print 'ISBN10: %s' % (_NormalizeIsbn(isbn)[0])


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
      _LookupIsbn('1573980137')
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
