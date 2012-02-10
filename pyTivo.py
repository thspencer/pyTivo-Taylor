#!/usr/bin/env python

import logging
import os
import sys
import time

if sys.version_info[0] != 2 or sys.version_info[1] < 4:
    print ('ERROR: pyTivo requires Python >= 2.4, < 3.0.\n')
    sys.exit(1)

import beacon
import config
import httpserver
from plugin import GetPlugin

def exceptionLogger(*args):
    sys.excepthook = sys.__excepthook__
    logging.getLogger('pyTivo').error('Exception in pyTivo', exc_info=args)

def setup(in_service=False):
    config.init(sys.argv[1:])
    config.init_logging()
    sys.excepthook = exceptionLogger

    port = config.getPort()

    httpd = httpserver.TivoHTTPServer(('', int(port)),
        httpserver.TivoHTTPHandler)

    logger = logging.getLogger('pyTivo')

    for section, settings in config.getShares():
        httpd.add_container(section, settings)
        # Precaching of files: does a recursive list of base path
        if settings.get('precache', 'False').lower() == 'true':
            plugin = GetPlugin(settings.get('type'))
            if hasattr(plugin, 'pre_cache'):
                logger.info('Pre-caching the ' + section + ' share.')
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
    b.add_service('TiVoMediaServer:%s/http' % port)
    b.start()
    if 'listen' in config.getBeaconAddresses():
        b.listen()

    httpd.set_beacon(b)
    httpd.set_service_status(in_service)

    logger.info('pyTivo is ready.')
    return httpd

def serve(httpd):
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass

def mainloop():
    httpd = setup()
    serve(httpd)
    httpd.beacon.stop()
    return httpd.restart 

if __name__ == '__main__':
    while mainloop():
        time.sleep(5) 
