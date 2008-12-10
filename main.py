#!/usr/bin/env python

import re
import cgi
import gzip
import time
import logging
import wsgiref.handlers
import datetime
from rfc822 import formatdate
from StringIO import StringIO
from django.utils import simplejson
from BeautifulSoup import BeautifulSoup

from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.api import memcache
from google.appengine.api import urlfetch

class Page(db.Model):
  url = db.StringProperty(required=True)
  title = db.StringProperty(required=True)
  datetime = db.DateTimeProperty(auto_now=True)

class MainHandler(webapp.RequestHandler):
  def get(self):
    url = cgi.escape(self.request.get('url'))
    callback = cgi.escape(self.request.get('callback'))
    obj = {}
    fetch = False
    error = None
    title = ''

#    for debugging
#    memcache.flush_all()
    
    if url:
      # Yeah, why re-fetch myself?
      if url == 'http://localhost:8080/' or url == 'http://json-pagetitle.appspot.com/':
        json = '{\n    "title": "json-pagetitle"\n}'
      
      else:
        json = memcache.get(url)
      
        if json is None:
          logging.info('The url is NOT in memcache')
          page = Page.gql('WHERE url = :1', url)

          if page.count() != 0: # Stored in DateStore
            logging.info('The url is in datastore')
            d = page[0].datetime
            modifiedsince = formatdate(time.mktime(d.timetuple()))
            headers = {
              'If-Modified-Since': modifiedsince,
            }
            try:
              result = urlfetch.fetch(url, headers=headers, allow_truncated=True)
              if result.status_code == 304: # Not Modified
                logging.info('The page is NOT modified')
                title = page[0].title
              else:
                logging.info('The page is modified')
                fetch = True
            except urlfetch.Error:
              logging.error('urlfetch error')
              error = 1
          else:
            logging.info('The url is NOT in datastore')
            fetch = True
        
          if fetch:
            try:
              headers = {
                'Accept-Encoding': 'gzip'
              }
              result = urlfetch.fetch(url, headers=headers, allow_truncated=True)
              if result.status_code == 200:
                logging.info('The page exists')
                contenttype = result.headers.get('Content-Type')
                ishtml = re.compile('text\/html|application\/xhtml\+xml').match(contenttype)
                if ishtml:
                  logging.info('The page is (X)HTML')
                  contentencoding = result.headers.get('Content-Encoding')
                  if contentencoding == 'gzip':
                    logging.info('The page is Gzipped')
                    s = StringIO(result.content)
                    content = gzip.GzipFile(fileobj=s).read()
                  else:
                    logging.info('The page is NOT Gzipped')
                    content = result.content
                  soup = BeautifulSoup(content)
                  if soup.title:
                    logging.debug('The page has a title')
                    title = soup.title.string.strip()
                  else:
                    logging.debug('The page doesn\'t have a title')
                  # Save to DataStore
                  if title:
                    logging.debug('Storing title for the url in datastore')
                    if page.count() != 0:
                      page[0].title = title
                    else:
                      page = Page(
                        url = url,
                        title = title
                      )
                    db.put(page)
                else:
                  logging.info('The page is NOT (X)HTML')
                  error = 3
              else:
                logging.info('The page doesn\'t exist')
                error = 2
                obj['status_code'] = result.status_code
            except urlfetch.Error:
              logging.error('urlfetch error')
              error = 1
              
          obj['title'] = title
          if error: obj['error'] = 'ApplicationError: ' + str(error)
          json = simplejson.dumps(obj, sort_keys=True, indent=4)
          # Save json output to Memcache, if there's no error
          if not error:
            logging.debug('Adding json output to memcache')
            memcache.add(url, json, 3600*3) # 3 hours
        else:
          logging.info('The url is in memcache')

      if callback:
        logging.info('Adding callback to JSON')
        exp = re.compile('^[A-Za-z_$][A-Za-z0-9._$]*?$')
        match = exp.match(callback)
        if match: json = callback + '(' + json + ')'
      
      if not error:
        d = datetime.datetime.utcnow() + datetime.timedelta(hours=3)
        expires = formatdate(time.mktime(d.timetuple()))
        self.response.headers['Expires'] = expires
      
      self.response.headers['Content-Type'] = 'application/javascript; charset=utf-8'
      self.response.out.write(json)
      
    else:
      self.response.out.write("""
      <!DOCTYPE html>
      <title>json-pagetitle</title>
      <h1>json-pagetitle</h1>
      <p>JSON (and JSON-P) API for fetching the title of the web page of a URL.
      <ul>
          <li><a href="/?url=http://www.google.com/">/?url=http://www.google.com/</a>
          <li><a href="/?url=http://www.yahoo.com/&amp;callback=foo">/?url=http://www.yahoo.com/&amp;callback=foo</a>
      </ul>
      <p>Inspired by <a href="http://json-head.appspot.com/">json-head</a> and <a href="http://json-time.appspot.com/">json-time</a>. You may also like <a href="http://json-longurl.appspot.com/">json-longurl</a>. <a href="http://json-pagetitle.googlecode.com/">Google Code</a>.
      """)

def main():
  application = webapp.WSGIApplication(
    [('/', MainHandler)],
    debug=True)
  wsgiref.handlers.CGIHandler().run(application)

if __name__ == '__main__':
  main()
