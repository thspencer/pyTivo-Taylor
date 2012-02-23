import cookielib
import logging
import os
import subprocess
import thread
import time
import urllib2
import urlparse
from urllib import quote, unquote
from xml.dom import minidom
from xml.sax.saxutils import escape

from Cheetah.Template import Template

import config
import metadata
from plugin import EncodeUnicode, Plugin

logger = logging.getLogger('pyTivo.togo')
tag_data = metadata.tag_data

SCRIPTDIR = os.path.dirname(__file__)

CLASS_NAME = 'ToGo'

# Some error/status message templates

MISSING = """<h3>Missing Data</h3> <p>You must set both "tivo_mak" and 
"togo_path" before using this function.</p>"""

TRANS_QUEUE = """<h3>Queued for Transfer</h3> <p>%s</p> <p>queued for 
transfer to:</p> <p>%s</p>"""

TRANS_STOP = """<h3>Transfer Stopped</h3> <p>Your transfer of:</p> 
<p>%s</p> <p>has been stopped.</p>"""

UNQUEUE = """<h3>Removed from Queue</h3> <p>%s</p> <p>has been removed 
from the queue.</p>"""

UNABLE = """<h3>Unable to Connect to TiVo</h3> <p>pyTivo was unable to 
connect to the TiVo at %s.</p> <p>This is most likely caused by an 
incorrect Media Access Key. Please return to the Web Configuration page 
and double check your <b>tivo_mak</b> setting.</p>"""

# Preload the templates
def tmpl(name):
    return file(os.path.join(SCRIPTDIR, 'templates', name), 'rb').read()

CONTAINER_TEMPLATE_MOBILE = tmpl('npl_mob.tmpl')
CONTAINER_TEMPLATE = tmpl('npl.tmpl')

status = {} # Global variable to control download threads
tivo_cache = {} # Cache of TiVo NPL
queue = {} # Recordings to download -- list per TiVo
basic_meta = {} # Data from NPL, parsed, indexed by progam URL

auth_handler = urllib2.HTTPDigestAuthHandler()
cj = cookielib.LWPCookieJar()
tivo_opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cj), 
                                   auth_handler)

class ToGo(Plugin):
    CONTENT_TYPE = 'text/html'

    def tivo_open(self, url):
        # Loop just in case we get a server busy message
        while True:
            try:
                # Open the URL using our authentication/cookie opener
                return tivo_opener.open(url)

            # Do a retry if the TiVo responds that the server is busy
            except urllib2.HTTPError, e:
                if e.code == 503:
                    time.sleep(5)
                    continue

                # Throw the error otherwise
                raise

    def NPL(self, handler, query):
        global basic_meta
        shows_per_page = 50 # Change this to alter the number of shows returned
        cname = query['Container'][0].split('/')[0]
        folder = ''
        has_tivodecode = bool(config.get_bin('tivodecode'))
        togo_mpegts = config.get_server('togo_mpegts', 'False').lower()
        useragent = handler.headers.getheader('User-Agent', '')

        if 'TiVo' in query:
            tivoIP = query['TiVo'][0]
            tsn = config.tivos_by_ip(tivoIP)
            tivo_name = config.tivo_names[tsn]
            tivo_mak = config.get_tsn('tivo_mak', tsn)
            theurl = ('https://' + tivoIP +
                      '/TiVoConnect?Command=QueryContainer&ItemCount=' +
                      str(shows_per_page) + '&Container=/NowPlaying')
            if 'Folder' in query:
                folder += query['Folder'][0]
                theurl += '/' + folder
            if 'AnchorItem' in query:
                theurl += '&AnchorItem=' + quote(query['AnchorItem'][0])
            if 'AnchorOffset' in query:
                theurl += '&AnchorOffset=' + query['AnchorOffset'][0]

            if (theurl not in tivo_cache or
                (time.time() - tivo_cache[theurl]['thepage_time']) >= 60):
                # if page is not cached or old then retreive it
                auth_handler.add_password('TiVo DVR', tivoIP, 'tivo', tivo_mak)
                try:
                    page = self.tivo_open(theurl)
                except IOError, e:
                    handler.redir(UNABLE % tivoIP, 10)
                    return
                tivo_cache[theurl] = {'thepage': minidom.parse(page),
                                      'thepage_time': time.time()}
                page.close()

            xmldoc = tivo_cache[theurl]['thepage']
            items = xmldoc.getElementsByTagName('Item')
            TotalItems = tag_data(xmldoc, 'Details/TotalItems')
            ItemStart = tag_data(xmldoc, 'ItemStart')
            ItemCount = tag_data(xmldoc, 'ItemCount')
            FirstAnchor = tag_data(items[0], 'Links/Content/Url')

            data = []
            for item in items:
                entry = {}
                entry['ContentType'] = tag_data(item, 'ContentType')
                for tag in ('CopyProtected', 'UniqueId'):
                    value = tag_data(item, tag)
                    if value:
                        entry[tag] = value
                if entry['ContentType'] == 'x-tivo-container/folder':
                    entry['Title'] = tag_data(item, 'Title')
                    entry['TotalItems'] = tag_data(item, 'TotalItems')
                    lc = tag_data(item, 'LastCaptureDate')
                    if not lc:
                        lc = tag_data(item, 'LastChangeDate')
                    entry['LastChangeDate'] = time.strftime('%b %d, %Y',
                        time.localtime(int(lc, 16)))
                else:
                    keys = {'Icon': 'Links/CustomIcon/Url',
                            'Url': 'Links/Content/Url',
                            'SourceSize': 'Details/SourceSize',
                            'Duration': 'Details/Duration',
                            'CaptureDate': 'Details/CaptureDate'}
                    for key in keys:
                        value = tag_data(item, keys[key])
                        if value:
                            entry[key] = value

                    entry['SourceSize'] = ( '%.3f GB' %
                        (float(entry['SourceSize']) / (1024 ** 3)) )

                    dur = int(entry['Duration']) / 1000
                    entry['Duration'] = ( '%02d:%02d:%02d' %
                        (dur / 3600, (dur % 3600) / 60, dur % 60) )

                    entry['CaptureDate'] = time.strftime('%b %d, %Y',
                        time.localtime(int(entry['CaptureDate'], 16)))

                    url = entry['Url']
                    if url in basic_meta:
                        entry.update(basic_meta[url])
                    else:
                        basic_data = metadata.from_container(item)
                        entry.update(basic_data)
                        basic_meta[url] = basic_data

                data.append(entry)
        else:
            data = []
            tivoIP = ''
            TotalItems = 0
            ItemStart = 0
            ItemCount = 0
            FirstAnchor = ''

        cname = query['Container'][0].split('/')[0]
        
        if useragent.lower().find('mobile') > 0:
            t = Template(CONTAINER_TEMPLATE_MOBILE, filter=EncodeUnicode)
        else:
            t = Template(CONTAINER_TEMPLATE, filter=EncodeUnicode)
        t.escape = escape
        t.quote = quote
        t.folder = folder
        t.status = status
        if tivoIP in queue:
            t.queue = queue[tivoIP]
        t.has_tivodecode = has_tivodecode
        t.togo_mpegts = togo_mpegts
        t.tname = tivo_name
        t.tivoIP = tivoIP
        t.container = cname
        t.data = data
        t.len = len
        t.TotalItems = int(TotalItems)
        t.ItemStart = int(ItemStart)
        t.ItemCount = int(ItemCount)
        t.FirstAnchor = quote(FirstAnchor)
        t.shows_per_page = shows_per_page
        handler.send_response(200)
        handler.send_header('Content-Type', 'text/html; charset=utf-8')
        handler.send_header('Refresh', '300')
        handler.send_header('Expires', '0')
        handler.end_headers()
        handler.wfile.write(t)

    def get_tivo_file(self, tivoIP, url, mak, togo_path):
        # global status
        status[url].update({'running': True, 'queued': False})

        parse_url = urlparse.urlparse(url)

        name = unquote(parse_url[2])[10:].split('.')
        id = unquote(parse_url[4]).split('id=')[1]
        name.insert(-1, ' - ' + id + '.')
        if status[url]['decode']:
            name[-1] = 'mpg'
        outfile = os.path.join(togo_path, ''.join(name))

        if status[url]['save']:
            meta = basic_meta[url]
            details_url = 'https://%s/TiVoVideoDetails?id=%s' % (tivoIP, id)
            try:
                handle = self.tivo_open(details_url)
                meta.update(metadata.from_details(handle))
                handle.close()
            except:
                pass
            metafile = open(outfile + '.txt', 'w')
            metadata.dump(metafile, meta)
            metafile.close()

        auth_handler.add_password('TiVo DVR', url, 'tivo', mak)
        try:
            if status[url]['ts_format']:
                handle = self.tivo_open('%s&Format=video/x-tivo-mpeg-ts' % url)
            else:
                handle = self.tivo_open(url)
        except urllib2.HTTPError, e:
            status[url]['running'] = False
            status[url]['error'] = e.code
            logger.error(e.code)
            return
        except urllib2.URLError, e:
            status[url]['running'] = False
            status[url]['error'] = e.reason
            logger.error(e.reason)
            return

        tivo_name = config.tivo_names[config.tivos_by_ip(tivoIP)]

        logger.info('[%s] Start getting "%s" from %s' %
                    (time.strftime('%d/%b/%Y %H:%M:%S'), outfile, tivo_name))

        if status[url]['decode']:
            tivodecode_path = config.get_bin('tivodecode')
            tcmd = [tivodecode_path, '-m', mak, '-o', outfile, '-']
            tivodecode = subprocess.Popen(tcmd, stdin=subprocess.PIPE,
                                          bufsize=(512 * 1024))
            f = tivodecode.stdin
        else:
            f = open(outfile, 'wb')
        length = 0
        start_time = time.time()
        last_interval = start_time
        now = start_time
        try:
            while status[url]['running']:
                output = handle.read(1024000)
                if not output:
                    break
                length += len(output)
                f.write(output)
                now = time.time()
                elapsed = now - last_interval
                if elapsed >= 5:
                    status[url]['rate'] = '%.2f Mb/s' % (length * 8.0 / 
                        (elapsed * 1024 * 1024))
                    status[url]['size'] += length
                    length = 0
                    last_interval = now
            if status[url]['running']:
                status[url]['finished'] = True
        except Exception, msg:
            status[url]['running'] = False
            logger.info(msg)
        handle.close()
        f.close()
        status[url]['size'] += length
        if status[url]['running']:
            mega_elapsed = (now - start_time) * 1024 * 1024
            if mega_elapsed < 1:
                mega_elapsed = 1
            size = status[url]['size']
            rate = size * 8.0 / mega_elapsed
            logger.info('[%s] Done getting "%s" from %s, %d bytes, %.2f Mb/s' %
                        (time.strftime('%d/%b/%Y %H:%M:%S'), outfile,
                         tivo_name, size, rate))
            status[url]['running'] = False
        else:
            os.remove(outfile)
            if status[url]['save']:
                os.remove(outfile + '.txt')
            logger.info('[%s] Transfer of "%s" from %s aborted' %
                        (time.strftime('%d/%b/%Y %H:%M:%S'), outfile,
                         tivo_name))
            del status[url]

    def process_queue(self, tivoIP, mak, togo_path):
        while queue[tivoIP]:
            time.sleep(5)
            url = queue[tivoIP][0]
            self.get_tivo_file(tivoIP, url, mak, togo_path)
            queue[tivoIP].pop(0)
        del queue[tivoIP]

    def ToGo(self, handler, query):
        togo_path = config.get_server('togo_path')
        for name, data in config.getShares():
            if togo_path == name:
                togo_path = data.get('path')
        if togo_path:
            tivoIP = query['TiVo'][0]
            tsn = config.tivos_by_ip(tivoIP)
            tivo_mak = config.get_tsn('tivo_mak', tsn)
            urls = query.get('Url', [])
            decode = 'decode' in query
            save = 'save' in query
            ts_format = 'ts_format' in query
            for theurl in urls:
                status[theurl] = {'running': False, 'error': '', 'rate': '',
                                  'queued': True, 'size': 0, 'finished': False,
                                  'decode': decode, 'save': save, 'ts_format' : ts_format}
                if tivoIP in queue:
                    queue[tivoIP].append(theurl)
                else:
                    queue[tivoIP] = [theurl]
                    thread.start_new_thread(ToGo.process_queue,
                                            (self, tivoIP, tivo_mak, togo_path))
                logger.info('[%s] Queued "%s" for transfer to %s' %
                            (time.strftime('%d/%b/%Y %H:%M:%S'),
                             unquote(theurl), togo_path))
            urlstring = '<br>'.join([unquote(x) for x in urls])
            message = TRANS_QUEUE % (urlstring, togo_path)
        else:
            message = MISSING
        handler.redir(message, 5)

    def ToGoStop(self, handler, query):
        theurl = query['Url'][0]
        status[theurl]['running'] = False
        handler.redir(TRANS_STOP % unquote(theurl))

    def Unqueue(self, handler, query):
        theurl = query['Url'][0]
        tivoIP = query['TiVo'][0]
        del status[theurl]
        queue[tivoIP].remove(theurl)
        logger.info('[%s] Removed "%s" from queue' %
                    (time.strftime('%d/%b/%Y %H:%M:%S'),
                     unquote(theurl)))
        handler.redir(UNQUEUE % unquote(theurl))
