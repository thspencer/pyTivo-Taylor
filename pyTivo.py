#!/usr/bin/env python

import logging
import logging.config
import os
import ConfigParser
import beacon, httpserver, os, sys
import config
from plugin import GetPlugin

def init_logging():
    config.config_files
    p = os.path.dirname(__file__)

    if config.config.has_section('loggers') and\
      config.config.has_section('handlers') and\
      config.config.has_section('formatters'):

        logging.config.fileConfig(config.config_files)

    elif config.getDebug():
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

init_logging()

port = config.getPort()

httpd = httpserver.TivoHTTPServer(('', int(port)), httpserver.TivoHTTPHandler)

for section, settings in config.getShares():
    httpd.add_container(section, settings)
    # Precaching of files: does a recursive list of base path
    if settings.get('precache', 'False').lower() == 'true':
        plugin = GetPlugin(settings.get('type'))
        if hasattr(plugin, 'pre_cache'):
            print 'Pre-caching the', section, 'share.'
            pre_cache_filter = getattr(plugin, 'pre_cache')

            def build_recursive_list(path):
                try:
                    for f in os.listdir(path):
                        f = os.path.join(path, f)
                        if os.path.isdir(f):
                            build_recursive_list(f)
                        else:
                            pre_cache_filter(f)
                except:
                    pass

            build_recursive_list(settings.get('path'))

b = beacon.Beacon()
b.add_service('TiVoMediaServer:' + str(port) + '/http')
b.start()
if 'listen' in config.getBeaconAddresses():
    b.listen()

logging.getLogger('pyTivo').info('pyTivo is ready.')

try:
    httpd.set_beacon(b)
    httpd.serve_forever()
except KeyboardInterrupt:
    b.stop()
