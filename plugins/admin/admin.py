import cookielib
import os
import socket
import re
import sys
import thread
import time
import urllib2
from urllib import unquote_plus, quote, unquote
from urlparse import urlparse
from xml.dom import minidom

from lrucache import LRUCache
from Cheetah.Template import Template
import buildhelp
import config
import logging
from plugin import EncodeUnicode, Plugin

SCRIPTDIR = os.path.dirname(__file__)

CLASS_NAME = 'Admin'

# Some error/status message templates

MISSING = """<h3>Missing Data.</h3>  <br>
You must set both "tivo_mak" and "togo_path" before using this 
function.<br>
The <a href="/TiVoConnect?Command=%s&Container=%s&TiVo=%s">ToGo</a> page 
will reload in 10 seconds."""

RESET_MSG = """<h3>The pyTivo Server has been soft reset.</h3>  <br>
pyTivo has reloaded the pyTivo.conf file and all changes should now be 
in effect. <br>
The <a href="/TiVoConnect?Command=%s&Container=%s">previous</a> page 
will reload in 3 seconds."""

SETTINGS1 = """<h3>Your Settings have been saved.</h3>  <br>
Your settings have been saved to the pyTivo.conf file. However you will 
need to do a <b>Soft Reset</b> before these changes will take effect.<br>
The <a href="/TiVoConnect?Command=Admin&Container=%s">Admin</a> page 
will reload in 10 seconds."""

SETTINGS2 = """<h3>Your Settings have been saved.</h3>  <br>
Your settings have been saved to the pyTivo.conf file. pyTivo will now 
do a <b>Soft Reset</b> to allow these changes to take effect.<br>
The <a href="/TiVoConnect?last_page=NPL&Command=Reset&Container=%s">Reset</a> 
will occur in 2 seconds."""

TRANS_INIT = """<h3>Transfer Initiated.</h3>  <br>
You selected transfer has been initiated.<br>
The <a href="/TiVoConnect?Command=%s&Container=%s&TiVo=%s">ToGo</a> page 
will reload in 3 seconds."""

TRANS_STOP = """<h3>Transfer Stopped.</h3>  <br>
Your transfer has been stopped.<br>
The <a href="/TiVoConnect?Command=%s&Container=%s&TiVo=%s">ToGo</a> page 
will reload in 3 seconds."""

UNABLE = """<h3>Unable to Connect to TiVo.</h3>  <br>
pyTivo was unable to connect to the TiVo at %s</br>
This most likely caused by an incorrect Media Access Key.  Please return 
to the ToGo page and double check your Media Access Key.<br>
The <a href="/TiVoConnect?Command=NPL&Container=%s">ToGo</a> page will
reload in 20 seconds."""

# Preload the templates
trname = os.path.join(SCRIPTDIR, 'templates', 'redirect.tmpl')
tsname = os.path.join(SCRIPTDIR, 'templates', 'settings.tmpl')
tnname = os.path.join(SCRIPTDIR, 'templates', 'npl.tmpl')
REDIRECT_TEMPLATE = file(trname, 'rb').read()
SETTINGS_TEMPLATE = file(tsname, 'rb').read()
NPL_TEMPLATE = file(tnname, 'rb').read()

# Something to strip
TRIBUNE_CR = ' Copyright Tribune Media Services, Inc.'

status = {} # Global variable to control download threads
tivo_cache = {} # Cache of TiVo NPL

def tag_data(element, tag):
    for name in tag.split('/'):
        new_element = element.getElementsByTagName(name)
        if not new_element:
            return ''
        element = new_element[0]
    return element.firstChild.data

class Admin(Plugin):
    CONTENT_TYPE = 'text/html'

    def Reset(self, handler, query):
        config.reset()
        handler.server.reset()
        if 'last_page' in query:
            last_page = query['last_page'][0]
        else:
            last_page = 'Admin'

        cname = query['Container'][0].split('/')[0]
        t = Template(REDIRECT_TEMPLATE)
        t.time = '3'
        t.url = '/TiVoConnect?Command='+ last_page +'&Container=' + quote(cname)
        t.text = RESET_MSG % (quote(last_page), quote(cname))
        handler.send_response(200)
        handler.end_headers()
        handler.wfile.write(t)
        logging.getLogger('pyTivo.admin').info('pyTivo has been soft reset.')

    def Admin(self, handler, query):
        # Read config file new each time in case there was any outside edits
        config.reset()

        shares_data = []
        for section in config.config.sections():
            if not (section.startswith('_tivo_')
                    or section.startswith('Server')):
                if (not(config.config.has_option(section, 'type')) or
                        config.config.get(section, 'type').lower() != 'admin'):
                    shares_data.append((section,
                                        dict(config.config.items(section,
                                                                 raw=True))))

        cname = query['Container'][0].split('/')[0]
        t = Template(SETTINGS_TEMPLATE, filter=EncodeUnicode)
        t.container = cname
        t.quote = quote
        t.server_data = dict(config.config.items('Server', raw=True))
        t.server_known = buildhelp.getknown('server')
        if config.config.has_section('_tivo_HD'):
            t.hd_tivos_data = dict(config.config.items('_tivo_HD', raw=True))
        else:
            t.hd_tivos_data = {}
        t.hd_tivos_known = buildhelp.getknown('hd_tivos')
        if config.config.has_section('_tivo_SD'):
            t.sd_tivos_data = dict(config.config.items('_tivo_SD', raw=True))
        else:
            t.sd_tivos_data = {}
        t.sd_tivos_known = buildhelp.getknown('sd_tivos')
        t.shares_data = shares_data
        t.shares_known = buildhelp.getknown('shares')
        t.tivos_data = [(section, dict(config.config.items(section, raw=True)))
                        for section in config.config.sections()
                        if section.startswith('_tivo_')
                        and not section.startswith('_tivo_SD')
                        and not section.startswith('_tivo_HD')]
        t.tivos_known = buildhelp.getknown('tivos')
        t.help_list = buildhelp.gethelp()
        handler.send_response(200)
        handler.end_headers()
        handler.wfile.write(t)

    def UpdateSettings(self, handler, query):
        config.reset()
        for section in ['Server', '_tivo_SD', '_tivo_HD']:
            for key in query:
                if key.startswith(section + '.'):
                    _, option = key.split('.')
                    if not config.config.has_section(section):
                        config.config.add_section(section)
                    if option == 'new__setting':
                        new_setting = query[key][0]
                    elif option == 'new__value':
                        new_value = query[key][0]
                    elif query[key][0] == ' ':
                        config.config.remove_option(section, option)
                    else:
                        config.config.set(section, option, query[key][0])
            if not(new_setting == ' ' and new_value == ' '):
                config.config.set(section, new_setting, new_value)

        sections = query['Section_Map'][0].split(']')
        sections.pop() # last item is junk
        for section in sections:
            ID, name = section.split('|')
            if query[ID][0] == 'Delete_Me':
                config.config.remove_section(name)
                continue
            if query[ID][0] != name:
                config.config.remove_section(name)
                config.config.add_section(query[ID][0])
            for key in query:
                if key.startswith(ID + '.'):
                    _, option = key.split('.')
                    if option == 'new__setting':
                        new_setting = query[key][0]
                    elif option == 'new__value':
                        new_value = query[key][0]
                    elif query[key][0] == ' ':
                        config.config.remove_option(query[ID][0], option)
                    else:
                        config.config.set(query[ID][0], option, query[key][0])
            if not(new_setting == ' ' and new_value == ' '):
                config.config.set(query[ID][0], new_setting, new_value)
        if query['new_Section'][0] != ' ':
            config.config.add_section(query['new_Section'][0])
        config.write()

        cname = query['Container'][0].split('/')[0]
        t = Template(REDIRECT_TEMPLATE)
        t.time = '10'
        t.url = '/TiVoConnect?Command=Admin&Container=' + quote(cname)
        t.text = SETTINGS1 % quote(cname)
        handler.send_response(200)
        handler.end_headers()
        handler.wfile.write(t)

    def NPL(self, handler, query):
        shows_per_page = 50 # Change this to alter the number of shows returned
        cname = query['Container'][0].split('/')[0]
        folder = ''
        AnchorItem = ''
        AnchorOffset = ''
        tivo_mak = config.get_server('tivo_mak')
        for name, data in config.getShares():
            if cname == name:
                togo_path = data.get('togo_path', '')
                if not tivo_mak:
                    tivo_mak = data.get('tivo_mak', '')

        if 'TiVo' in query:
            tivoIP = query['TiVo'][0]
            theurl = ('https://' + tivoIP +
                      '/TiVoConnect?Command=QueryContainer&ItemCount=' +
                      str(shows_per_page) + '&Container=/NowPlaying')
            if 'Folder' in query:
                folder += str(query['Folder'][0])
                theurl += '/' + folder
            if 'AnchorItem' in query:
                AnchorItem += str(query['AnchorItem'][0])
                theurl += '&AnchorItem=' + quote(AnchorItem)
            if 'AnchorOffset' in query:
                AnchorOffset += str(query['AnchorOffset'][0])
                theurl += '&AnchorOffset=' + AnchorOffset

            r = urllib2.Request(theurl)
            auth_handler = urllib2.HTTPDigestAuthHandler()
            auth_handler.add_password('TiVo DVR', tivoIP, 'tivo', tivo_mak)
            opener = urllib2.build_opener(auth_handler)
            urllib2.install_opener(opener)

            if (theurl not in tivo_cache or
                (tivo_cache[theurl]['thepage'] == '' or
                 (time.time() - tivo_cache[theurl]['thepage_time']) >= 60)):
                # if page is not cached, empty or old then retreive it
                try:
                    page = urllib2.urlopen(r)
                except IOError, e:
                    t = Template(REDIRECT_TEMPLATE)
                    t.time = '20'
                    t.url = '/TiVoConnect?Command=NPL&Container=' + quote(cname)
                    t.text = UNABLE % (tivoIP, quote(cname))
                    handler.send_response(200)
                    handler.end_headers()
                    handler.wfile.write(t)
                    return
                tivo_cache[theurl] = {'thepage': page.read(),
                                      'thepage_time': time.time()}
                page.close()

            xmldoc = minidom.parseString(tivo_cache[theurl]['thepage'])
            items = xmldoc.getElementsByTagName('Item')
            TotalItems = tag_data(xmldoc, 'Details/TotalItems')
            ItemStart = tag_data(xmldoc, 'ItemStart')
            ItemCount = tag_data(xmldoc, 'ItemCount')
            FirstAnchor = tag_data(items[0], 'Links/Content/Url')

            data = []
            for item in items:
                entry = {}
                entry['Title'] = tag_data(item, 'Title')
                entry['ContentType'] = tag_data(item, 'ContentType')
                for tag in ('CopyProtected', 'UniqueId'):
                    value = tag_data(item, tag)
                    if value:
                        entry[tag] = value
                if entry['ContentType'] == 'x-tivo-container/folder':
                    entry['TotalItems'] = tag_data(item, 'TotalItems')
                    lc = int(tag_data(item, 'LastChangeDate'), 16)
                    entry['LastChangeDate'] = time.strftime('%b %d, %Y',
                                                            time.localtime(lc))
                else:
                    icon = tag_data(item, 'Links/CustomIcon/Url')
                    if icon:
                        entry['Icon'] = icon
                    url = tag_data(item, 'Links/Content/Url')
                    if url:
                        entry['Url'] = url
                    keys = ('SourceSize', 'Duration', 'CaptureDate',
                            'EpisodeTitle', 'Description',
                            'SourceChannel', 'SourceStation')
                    for key in keys:
                        entry[key] = tag_data(item, key)

                    entry['SourceSize'] = ( '%.3f GB' %
                        (float(entry['SourceSize']) / (1024 ** 3)) )

                    dur = int(entry['Duration']) / 1000
                    entry['Duration'] = ( '%02d:%02d:%02d' %
                        (dur / 3600, (dur % 3600) / 60, dur % 60) )

                    entry['CaptureDate'] = time.strftime('%b %d, %Y',
                        time.localtime(int(entry['CaptureDate'], 16)))

                    desc = entry['Description']
                    entry['Description'] = desc.replace(TRIBUNE_CR, '')

                data.append(entry)
        else:
            data = []
            tivoIP = ''
            TotalItems = 0
            ItemStart = 0
            ItemCount = 0
            FirstAnchor = ''

        cname = query['Container'][0].split('/')[0]
        t = Template(NPL_TEMPLATE, filter=EncodeUnicode)
        t.quote = quote
        t.folder = folder
        t.status = status
        t.tivo_mak = tivo_mak
        t.togo_path = togo_path
        t.tivos = config.tivos
        t.tivo_names = config.tivo_names
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
        handler.send_header('Content-Type', 'text/html')
        handler.end_headers()
        handler.wfile.write(t)

    def get_tivo_file(self, url, mak, tivoIP, outfile):
        # global status
        cj = cookielib.LWPCookieJar()

        # remove the port from the URL to avoid authentication errors
        parse_url = urlparse(url)
        newurl = 'http://%s%s?%s' % (parse_url[1].split(':')[0],
                                     parse_url[2], parse_url[4])
        r = urllib2.Request(newurl)
        auth_handler = urllib2.HTTPDigestAuthHandler()
        auth_handler.add_password('TiVo DVR', tivoIP, 'tivo', mak)
        opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cj),
                                      auth_handler)
        urllib2.install_opener(opener)

        try:
            handle = urllib2.urlopen(r)
        except IOError, e:
            # If we get "Too many transfers error" try a second time.  
            # For some reason urllib2 does not properly close 
            # connections when a transfer is canceled.
            if e.code == 503:
                try:
                    handle = urllib2.urlopen(r)
                except IOError, e:
                    status[url]['running'] = False
                    status[url]['error'] = e.code
                    return
            else:
                status[url]['running'] = False
                status[url]['error'] = e.code
                return

        f = open(outfile, 'wb')
        kilobytes = 0
        start_time = time.time()
        try:
            output = handle.read(1024000)
            while status[url]['running'] and output:
                kilobytes += 1000
                f.write(output)
                now = time.time()
                elapsed = now - start_time
                if elapsed >= 5:
                    status[url]['rate'] = int(kilobytes / elapsed)
                    status[url]['size'] += (kilobytes * 1024)
                    kilobytes = 0
                    start_time = now
                output = handle.read(1024000)
            if status[url]['running']:
                status[url]['finished'] = True
        except Exception, msg:
            logging.getLogger('pyTivo.admin').info(msg)
        finally:
            status[url]['running'] = False
            handle.close()
            f.close()

    def ToGo(self, handler, query):
        cname = query['Container'][0].split('/')[0]
        tivoIP = query['TiVo'][0]
        tivo_mak = config.get_server('tivo_mak')
        for name, data in config.getShares():
            if cname == name:
                togo_path = data.get('togo_path', '')
                if not tivo_mak:
                    tivo_mak = data.get('tivo_mak', '')
        t = Template(REDIRECT_TEMPLATE)
        command = query['Redirect'][0]
        params = (command, quote(cname), tivoIP)
        if tivo_mak and togo_path:
            theurl = query['Url'][0]
            parse_url = urlparse(theurl)
            name = unquote(parse_url[2])[10:].split('.')
            name.insert(-1," - " + unquote(parse_url[4]).split("id=")[1] + ".")
            outfile = os.path.join(togo_path, "".join(name))

            status[theurl] = {'running': True, 'error': '', 'rate': '',
                              'size': 0, 'finished': False}

            thread.start_new_thread(Admin.get_tivo_file,
                                    (self, theurl, tivo_mak, tivoIP, outfile))

            t.time = '3'
            t.text = TRANS_INIT % params
        else:
            t.time = '10'
            t.text = MISSING % params
        t.url = ('/TiVoConnect?Command=' + command + '&Container=' +
                 quote(cname) + '&TiVo=' + tivoIP)
        handler.send_response(200)
        handler.end_headers()
        handler.wfile.write(t)

    def ToGoStop(self, handler, query):
        theurl = query['Url'][0]
        status[theurl]['running'] = False

        cname = query['Container'][0].split('/')[0]
        tivoIP = query['TiVo'][0]
        command = query['Redirect'][0]
        t = Template(REDIRECT_TEMPLATE)
        t.time = '3'
        t.url = ('/TiVoConnect?Command=' + command + '&Container=' +
                 quote(cname) + '&TiVo=' + tivoIP)
        t.text = TRANS_STOP % (command, quote(cname), tivoIP)
        handler.send_response(200)
        handler.end_headers()
        handler.wfile.write(t)

    def SaveNPL(self, handler, query):
        config.reset()
        if 'tivo_mak' in query:
            config.config.set('Server', 'tivo_mak', query['tivo_mak'][0])
            config.config.remove_option(query['Container'][0], 'tivo_mak')
        if 'togo_path' in query:
            config.config.set(query['Container'][0], 'togo_path',
                              query['togo_path'][0])
        config.write()

        cname = query['Container'][0].split('/')[0]
        t = Template(REDIRECT_TEMPLATE)
        t.time = '2'
        t.url = ('/TiVoConnect?last_page=NPL&Command=Reset&Container=' +
                 quote(cname))
        t.text = SETTINGS2 % quote(cname)
        handler.send_response(200)
        handler.end_headers()
        handler.wfile.write(t)
