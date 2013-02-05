#!/usr/bin/env python

import logging
import os
import platform
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

def last_date():
    lasttime = -1
    path = os.path.dirname(__file__)
    if not path:
        path = '.'
    for root, dirs, files in os.walk(path):
        for name in files:
            if name.endswith('.py'):
                tm = os.stat(os.path.join(root, name)).st_mtime
                if tm > lasttime:
                    lasttime = tm

    return time.asctime(time.localtime(lasttime))

def get_cur_commit():
    pyTivo_dir = os.path.dirname(__file__)
    version_file = os.path.join(pyTivo_dir, 'version.txt')
    try:
        f = open(version_file, 'rt')
        cur_commit = f.read().strip('\r\n ') # strip out unwanted leading chars
        f.close()
        if not cur_commit:
            cur_commit = 'unknown'
    except:
        cur_commit = 'unknown'

    return cur_commit

def setup(in_service=False):
    config.init(sys.argv[1:])
    config.init_logging()
    sys.excepthook = exceptionLogger

    port = config.getPort()

    httpd = httpserver.TivoHTTPServer(('', int(port)),
        httpserver.TivoHTTPHandler)

    logger = logging.getLogger('pyTivo')
    commit = get_cur_commit()
    logger.info('Using commit: iluvatar-%s' % commit[:7])
    logger.info('Last modified: ' + last_date())
    logger.info('Python: ' + platform.python_version())
    logger.info('System: ' + platform.platform())

    for section, settings in config.getShares():
        httpd.add_container(section, settings)

    b = beacon.Beacon()
    b.add_service('TiVoMediaServer:%s/http' % port)
    b.start()
    if 'listen' in config.getBeaconAddresses():
        b.listen()

    httpd.set_beacon(b)
    httpd.set_service_status(in_service)
    config.config_check()

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
