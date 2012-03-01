import logging
import re
import struct
import time
from socket import *
from threading import Timer
from urllib import quote

import Zeroconf

import config
from plugin import GetPlugin

SHARE_TEMPLATE = '/TiVoConnect?Command=QueryContainer&Container=%s'
PLATFORM_MAIN = 'pyTivo'
PLATFORM_VIDEO = 'pc'    # For the nice icon

class ZCListener:
    def __init__(self, names):
        self.names = names

    def removeService(self, server, type, name):
        if name in self.names:
            self.names.remove(name)

    def addService(self, server, type, name):
        self.names.append(name)

class ZCBroadcast:
    def __init__(self, logger):
        """ Announce our shares via Zeroconf. """
        self.share_names = []
        self.share_info = []
        self.logger = logger
        self.rz = Zeroconf.Zeroconf()
        address = inet_aton(config.get_ip())
        port = int(config.getPort())
        for section, settings in config.getShares():
            ct = GetPlugin(settings['type']).CONTENT_TYPE
            if ct.startswith('x-container/'):
                if 'video' in ct:
                    platform = PLATFORM_VIDEO
                else:
                    platform = PLATFORM_MAIN
                logger.info('Registering: %s' % section)
                self.share_names.append(section)
                desc = {'path': SHARE_TEMPLATE % quote(section),
                        'platform': platform, 'protocol': 'http'}
                tt = ct.split('/')[1]
                info = Zeroconf.ServiceInfo('_%s._tcp.local.' % tt,
                    '%s._%s._tcp.local.' % (section, tt),
                    address, port, 0, 0, desc)
                self.rz.registerService(info)
                self.share_info.append(info)

    def scan(self):
        """ Look for TiVos using Zeroconf. """
        VIDS = '_tivo-videos._tcp.local.'
        names = []

        # Get the names of servers offering TiVo videos
        browser = Zeroconf.ServiceBrowser(self.rz, VIDS, ZCListener(names))

        # Give them half a second to respond
        time.sleep(0.5)

        # Now get the addresses -- this is the slow part
        for name in names:
            info = self.rz.getServiceInfo(VIDS, name)
            if info and 'TSN' in info.properties:
                tsn = info.properties['TSN']
                address = inet_ntoa(info.getAddress())
                config.tivos[tsn] = address
                name = name.replace('.' + VIDS, '')
                self.logger.info(name)
                config.tivo_names[tsn] = name

    def shutdown(self):
        self.logger.info('Unregistering: %s' % ' '.join(self.share_names))
        for info in self.share_info:
            self.rz.unregisterService(info)
        self.rz.close()

class Beacon:
    def __init__(self):
        self.UDPSock = socket(AF_INET, SOCK_DGRAM)
        self.UDPSock.setsockopt(SOL_SOCKET, SO_BROADCAST, 1)
        self.services = []

        if config.get_zc():
            logger = logging.getLogger('pyTivo.beacon')
            try:
                logger.info('Announcing shares...')
                self.bd = ZCBroadcast(logger)
            except:
                logger.error('Zeroconf failure')
                self.bd = None
            else:
                logger.info('Scanning for TiVos...')
                self.bd.scan()
        else:
            self.bd = None

    def add_service(self, service):
        self.services.append(service)
        self.send_beacon()

    def format_services(self):
        return ';'.join(self.services)

    def format_beacon(self, conntype, services=True):
        beacon = ['tivoconnect=1',
                  'swversion=1',
                  'method=%s' % conntype,
                  'identity=%s' % config.getGUID(),
                  'machine=%s' % gethostname(),
                  'platform=%s' % PLATFORM_MAIN]

        if services:
            beacon.append('services=' + self.format_services())
        else:
            beacon.append('services=TiVoMediaServer:0/http')

        return '\n'.join(beacon)

    def send_beacon(self):
        beacon_ips = config.getBeaconAddresses()
        for beacon_ip in beacon_ips.split():
            if beacon_ip != 'listen':
                try:
                    self.UDPSock.sendto(self.format_beacon('broadcast'),
                                        (beacon_ip, 2190))
                except error, e:
                    print e

    def start(self):
        self.send_beacon()
        self.timer = Timer(60, self.start)
        self.timer.start()

    def stop(self):
        self.timer.cancel()
        if self.bd:
            self.bd.shutdown()

    def listen(self):
        """ For the direct-connect, TCP-style beacon """
        import thread

        def server():
            TCPSock = socket(AF_INET, SOCK_STREAM)
            TCPSock.bind(('', 2190))
            TCPSock.listen(5)

            while True:
                # Wait for a connection
                client, address = TCPSock.accept()

                # Accept the client's beacon
                client_length = struct.unpack('!I', client.recv(4))[0]
                client_message = client.recv(client_length)

                # Send ours
                message = self.format_beacon('connected')
                client.send(struct.pack('!I', len(message)))
                client.send(message)
                client.close()

        thread.start_new_thread(server, ())

    def get_name(self, address):
        """ Exchange beacons, and extract the machine name. """
        our_beacon = self.format_beacon('connected', False)
        machine_name = re.compile('machine=(.*)\n').search

        try:
            tsock = socket()
            tsock.connect((address, 2190))

            tsock.send(struct.pack('!I', len(our_beacon)))
            tsock.send(our_beacon)

            length = struct.unpack('!I', tsock.recv(4))[0]
            tivo_beacon = tsock.recv(length)

            tsock.close()

            name = machine_name(tivo_beacon).groups()[0]
        except:
            name = address

        return name
