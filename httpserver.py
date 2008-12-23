import BaseHTTPServer
import SocketServer
import logging
import os
import re
import socket
import time
from cgi import parse_qs
from urllib import unquote_plus, quote, unquote
from urlparse import urlparse
from xml.sax.saxutils import escape

from Cheetah.Template import Template
import config
from plugin import GetPlugin

SCRIPTDIR = os.path.dirname(__file__)

class TivoHTTPServer(SocketServer.ThreadingMixIn, BaseHTTPServer.HTTPServer):
    containers = {}

    def __init__(self, server_address, RequestHandlerClass):
        BaseHTTPServer.HTTPServer.__init__(self, server_address,
                                           RequestHandlerClass)
        self.daemon_threads = True

    def add_container(self, name, settings):
        if self.containers.has_key(name) or name == 'TiVoConnect':
            raise "Container Name in use"
        try:
            settings['content_type'] = GetPlugin(settings['type']).CONTENT_TYPE
            self.containers[name] = settings
        except KeyError:
            print 'Unable to add container', name

    def reset(self):
        self.containers.clear()
        for section, settings in config.getShares():
            self.add_container(section, settings)

    def set_beacon(self, beacon):
        self.beacon = beacon

class TivoHTTPHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    tivos = {}
    tivo_names = {}

    def address_string(self):
        host, port = self.client_address[:2]
        return host

    def do_GET(self):
        tsn = self.headers.getheader('TiVo_TCD_ID',
                                     self.headers.getheader('tsn', ''))
        if tsn:
            ip = self.address_string()
            self.tivos[tsn] = ip

            if not tsn in self.tivo_names:
                self.tivo_names[tsn] = self.server.beacon.get_name(ip)

        basepath = unquote_plus(self.path).split('/')[1]

        ## Get File
        for name, container in self.server.containers.items():
            if basepath == name:
                plugin = GetPlugin(container['type'])
                plugin.send_file(self, container, name)
                return

        ## Not a file not a TiVo command fuck them
        if not self.path.startswith('/TiVoConnect'):
            self.infopage()
            return

        o = urlparse("http://fake.host" + self.path)
        query = parse_qs(o[4])

        mname = False
        if query.has_key('Command') and len(query['Command']) >= 1:

            command = query['Command'][0]

            # If we are looking at the root container
            if command == "QueryContainer" and \
               (not query.has_key('Container') or query['Container'][0] == '/'):
                self.root_container()
                return

            if query.has_key('Container'):
                # Dispatch to the container plugin
                basepath = unquote(query['Container'][0].split('/')[0])
                for name, container in self.server.containers.items():
                    if basepath == name:
                        plugin = GetPlugin(container['type'])
                        if hasattr(plugin, command):
                            method = getattr(plugin, command)
                            method(self, query)
                            return
                        else:
                            break

        # If we made it here it means we couldn't match the request to
        # anything.
        self.unsupported(query)

    def root_container(self):
        tsn = self.headers.getheader('TiVo_TCD_ID', '')
        tsnshares = config.getShares(tsn)
        tsncontainers = {}
        for section, settings in tsnshares:
            try:
                settings['content_type'] = \
                    GetPlugin(settings['type']).CONTENT_TYPE
                tsncontainers[section] = settings
            except Exception, msg:
                print section, '-', msg
        t = Template(file=os.path.join(SCRIPTDIR, 'templates',
                                       'root_container.tmpl'))
        t.containers = tsncontainers
        t.hostname = socket.gethostname()
        t.escape = escape
        t.quote = quote
        self.send_response(200)
        self.end_headers()
        self.wfile.write(t)

    def infopage(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        t = Template(file=os.path.join(SCRIPTDIR, 'templates',
                                       'info_page.tmpl'))
        t.admin = ''
        for section, settings in config.getShares():
            if 'type' in settings and settings['type'] == 'admin':
                t.admin += '<a href="/TiVoConnect?Command=Admin&Container=' + \
                           quote(section) + \
                           '">pyTivo Web Configuration</a><br>' + \
                           '<a href="/TiVoConnect?Command=NPL&Container=' + \
                           quote(section) + '">pyTivo ToGo</a><br>'
        if t.admin == '':
            t.admin = '<br><b>No Admin plugin installed in pyTivo.conf</b>' + \
                      '<br> If you wish to use the admin plugin add the ' + \
                      'following lines to pyTivo.conf<br><br>' + \
                      '[Admin]<br>type=admin'

        t.shares = 'Video shares:<br/>'
        for section, settings in config.getShares():
            if settings.get('type') == 'video':
                t.shares += '<a href="TiVoConnect?Command=QueryContainer&' + \
                            'Container=' + quote(section) + '">' + section + \
                            '</a><br/>'

        self.wfile.write(t)

    def unsupported(self, query):
        self.send_response(404)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        t = Template(file=os.path.join(SCRIPTDIR, 'templates',
                                       'unsupported.tmpl'))
        t.query = query
        self.wfile.write(t)

if __name__ == '__main__':
    def start_server():
        httpd = TivoHTTPServer(('', 9032), TivoHTTPHandler)
        httpd.add_container('test', 'x-container/tivo-videos',
                            r'C:\Documents and Settings\Armooo' +
                            r'\Desktop\pyTivo\test')
        httpd.serve_forever()

    start_server()
