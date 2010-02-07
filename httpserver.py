import BaseHTTPServer
import SocketServer
import cgi
import logging
import mimetypes
import os
import re
import socket
import time
from urllib import unquote_plus, quote
from xml.sax.saxutils import escape

from Cheetah.Template import Template
import config
from plugin import GetPlugin, GetPluginPath, EncodeUnicode

SCRIPTDIR = os.path.dirname(__file__)

VIDEO_FORMATS = """<?xml version="1.0" encoding="utf-8"?>
<TiVoFormats><Format>
<ContentType>video/x-tivo-mpeg</ContentType><Description/>
</Format></TiVoFormats>"""

RE_PLUGIN_CONTENT = re.compile(r'/plugin/([^/]+)/content/(.+)')

class TivoHTTPServer(SocketServer.ThreadingMixIn, BaseHTTPServer.HTTPServer):
    containers = {}

    def __init__(self, server_address, RequestHandlerClass):
        BaseHTTPServer.HTTPServer.__init__(self, server_address,
                                           RequestHandlerClass)
        self.daemon_threads = True
        self.logger = logging.getLogger('pyTivo')

    def add_container(self, name, settings):
        if name in self.containers or name == 'TiVoConnect':
            raise "Container Name in use"
        try:
            self.containers[name] = settings
        except KeyError:
            self.logger.error('Unable to add container ' + name)

    def reset(self):
        self.containers.clear()
        for section, settings in config.getShares():
            self.add_container(section, settings)

    def handle_error(self, request, client_address):
        self.logger.exception('Exception during request from %s' % 
                              (client_address,))

    def set_beacon(self, beacon):
        self.beacon = beacon

class TivoHTTPHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    def __init__(self, request, client_address, server):
        self.wbufsize = 0x10000
        BaseHTTPServer.BaseHTTPRequestHandler.__init__(self, request,
            client_address, server)

    def address_string(self):
        host, port = self.client_address[:2]
        return host

    def do_GET(self):
        tsn = self.headers.getheader('TiVo_TCD_ID',
                                     self.headers.getheader('tsn', ''))
        if not self.authorize(tsn):
            return
        if tsn:
            ip = self.address_string()
            config.tivos[tsn] = ip

            if not tsn in config.tivo_names or config.tivo_names[tsn] == tsn:
                config.tivo_names[tsn] = self.server.beacon.get_name(ip)

        if '?' in self.path:
            path, opts = self.path.split('?', 1)
            query = cgi.parse_qs(opts)
        else:
            path = self.path
            query = {}

        regm = RE_PLUGIN_CONTENT.match(path)

        if path == '/TiVoConnect':
            self.handle_query(query, tsn)
        elif regm != None:
            # Handle general plugin content requests of the form
            # /plugin/<plugin type>/content/<file>
            try:
                # Protect ourself from path exploits
                file_bits = regm.group(2).split('/')
                for bit in file_bits:
                    if bit == '..':
                        raise
            
                # Get the plugin path
                plugin_path = GetPluginPath(regm.group(1))
                
                # Build up the actual path based on the plugin path
                filen = os.path.join(plugin_path, 'content', *file_bits)

                # If it's not a file, then just error out
                if not os.path.isfile(filen):
                    raise
                
                # Read in the full file    
                handle = open(filen, 'rb')
                try:
                    text = handle.read()
                    handle.close()
                except:
                    handle.close()
                    raise
                
                # Send the header
                self.send_response(200)
                self.send_header('Content-type', mimetypes.guess_type(filen))
                self.send_header('Content-length', os.path.getsize(filen))
                self.end_headers()
                
                # Send the body of the file
                self.wfile.write(text)
            except:
                self.send_response(404)
                self.end_headers()
                self.wfile.write('File not found')
        else:
            ## Get File
            path = unquote_plus(path)
            basepath = path.split('/')[1]
            for name, container in self.server.containers.items():
                if basepath == name:
                    path = os.path.join(os.path.normpath(container['path']),
                                        os.path.normpath(path[len(name) + 2:]))
                    plugin = GetPlugin(container['type'])
                    plugin.send_file(self, path, query)
                    return

            ## Not a file not a TiVo command
            self.infopage()

    def do_POST(self):
        tsn = self.headers.getheader('TiVo_TCD_ID',
                                     self.headers.getheader('tsn', ''))
        if not self.authorize(tsn):
            return
        ctype, pdict = cgi.parse_header(self.headers.getheader('content-type'))
        if ctype == 'multipart/form-data':
            query = cgi.parse_multipart(self.rfile, pdict)
        else:
            length = int(self.headers.getheader('content-length'))
            qs = self.rfile.read(length)
            query = cgi.parse_qs(qs, keep_blank_values=1)
        self.handle_query(query, tsn)

    def handle_query(self, query, tsn):
        mname = False
        if 'Command' in query and len(query['Command']) >= 1:

            command = query['Command'][0]

            # If we are looking at the root container
            if (command == 'QueryContainer' and
                (not 'Container' in query or query['Container'][0] == '/')):
                self.root_container()
                return

            if 'Container' in query:
                # Dispatch to the container plugin
                basepath = query['Container'][0].split('/')[0]
                for name, container in config.getShares(tsn):
                    if basepath == name:
                        plugin = GetPlugin(container['type'])
                        if hasattr(plugin, command):
                            method = getattr(plugin, command)
                            method(self, query)
                            return
                        else:
                            break

            elif (command == 'QueryFormats' and 'SourceFormat' in query and
                  query['SourceFormat'][0].startswith('video')):
                self.send_response(200)
                self.send_header('Content-type', 'text/xml')
                self.end_headers()
                self.wfile.write(VIDEO_FORMATS)
                return

            elif command == 'FlushServer':
                # Does nothing -- included for completeness
                self.send_response(200)
                self.end_headers()
                return

        # If we made it here it means we couldn't match the request to
        # anything.
        self.unsupported(query)

    def authorize(self, tsn=None):
        # if allowed_clients is empty, we are completely open
        allowed_clients = config.getAllowedClients()
        if not allowed_clients or (tsn and config.isTsnInConfig(tsn)):
            return True
        client_ip = self.client_address[0]
        for allowedip in allowed_clients:
            if client_ip.startswith(allowedip):
                return True

        self.send_response(404)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write("Unauthorized.")
        return False

    def log_message(self, format, *args):
        self.server.logger.info("%s [%s] %s" % (self.address_string(),
                                self.log_date_time_string(), format%args))

    def root_container(self):
        tsn = self.headers.getheader('TiVo_TCD_ID', '')
        tsnshares = config.getShares(tsn)
        tsncontainers = []
        for section, settings in tsnshares:
            try:
                settings['content_type'] = \
                    GetPlugin(settings['type']).CONTENT_TYPE
                tsncontainers.append((section, settings))
            except Exception, msg:
                self.server.logger.error(section + ' - ' + str(msg))
        t = Template(file=os.path.join(SCRIPTDIR, 'templates',
                                       'root_container.tmpl'),
                     filter=EncodeUnicode)
        t.containers = tsncontainers
        t.hostname = socket.gethostname()
        t.escape = escape
        t.quote = quote
        self.send_response(200)
        self.send_header('Content-type', 'text/xml')
        self.end_headers()
        self.wfile.write(t)

    def infopage(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        t = Template(file=os.path.join(SCRIPTDIR, 'templates',
                                       'info_page.tmpl'))
        t.admin = ''

        if config.get_server('tivo_mak') and config.get_server('togo_path'):
            t.togo = '<br>Pull from TiVos:<br>'
        else:
            t.togo = ''

        if (config.get_server('tivo_username') and
            config.get_server('tivo_password')):
            t.shares = '<br>Push from video shares:<br>'
        else:
            t.shares = ''

        for section, settings in config.getShares():
            plugin_type = settings.get('type')
            if plugin_type == 'settings':
                t.admin += ('<a href="/TiVoConnect?Command=Settings&amp;' +
                            'Container=' + quote(section) +
                            '">Web Configuration</a><br>')
            elif plugin_type == 'togo' and t.togo:
                for tsn in config.tivos:
                    if tsn:
                        t.togo += ('<a href="/TiVoConnect?' +
                            'Command=NPL&amp;Container=' + quote(section) +  
                            '&amp;TiVo=' + config.tivos[tsn] + '">' + 
                            config.tivo_names[tsn] + '</a><br>')
            elif plugin_type == 'video' and t.shares:
                t.shares += ('<a href="TiVoConnect?Command=' +
                             'QueryContainer&amp;Container=' +
                             quote(section) + '">' + section + '</a><br>')

        self.wfile.write(t)

    def unsupported(self, query):
        self.send_response(404)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        t = Template(file=os.path.join(SCRIPTDIR, 'templates',
                                       'unsupported.tmpl'))
        t.query = query
        self.wfile.write(t)
