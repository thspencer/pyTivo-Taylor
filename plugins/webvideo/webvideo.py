from plugins.video.video import Video, VideoDetails
import mind
import config

import xmpp

import threading
import xml.etree.ElementTree as ElementTree

CLASS_NAME = 'WebVideo'


class WebVideo(Video):

    CONTENT_TYPE = 'x-not-for/tivo'

    def init(self):
        self.sem = threading.Semaphore(1)

        self.startXMPP()
        self.xmpp_cdsupdate()

    def startXMPP(self):
        m = mind.getMind()
        xmpp_info = m.getXMPPLoginInfo()

        jid=xmpp.protocol.JID(xmpp_info['username'] + '/pyTivo')
        cl=xmpp.Client(
            server=xmpp_info['server'],
            port=xmpp_info['port'],
        )

        cl.connect()
        cl.RegisterHandler('message', self.processMessage)
        cl.auth(user=jid.getNode(), password=config.getTivoPassword(), resource='pyTivo')

        cl.sendInitPresence(requestRoster=0)

        for user_name in xmpp_info['presence_list']:
            jid=xmpp.protocol.JID(user_name)
            cl.sendPresence(jid)


        t = threading.Thread(target=self.processXMPP, args=(cl,))
        t.setDaemon(True)
        t.start()

    def processXMPP(self, client):
        while client.Process():
            pass

    def processMessage(self, sess,mess):
        xmpp_action = ElementTree.fromstring(mess.getBody())

        method_name = 'xmpp_' + xmpp_action.findtext('action').lower()
        if not hasattr(self, method_name):
            return False

        method = getattr(self, method_name)
        method(xmpp_action)


    def xmpp_cdsupdate(self, xml=None):
        m = mind.getMind()
        for request in m.getDownloadRequests():
            t = threading.Thread(target=self.processDlRequest, args=(request,))
            t.setDaemon(True)
            t.start()

    def processDlRequest(self, data):
        import shutil
        import os.path
        import urllib2
        import urllib

        for share_name, settings in config.getShares():
            if settings['type'] == 'webvideo':
                break

        self.sem.acquire()

        path = settings['path']
        file_name = os.path.join(path, '%s-%s' % (data['bodyOfferId'] ,data['url'].split('/')[-1]))

        print 'downloading %s to %s' % (data['url'], file_name)

        outfile = open(file_name, 'wb')

        infile = urllib2.urlopen(data['url'])
        shutil.copyfileobj(infile, outfile)

        print 'done downloading %s to %s' % (data['url'], file_name)

        tsn = data['bodyId']
        file_info = VideoDetails()
        file_info.update(self.metadata_full(file_name, tsn))

        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('tivo.com',123))
        ip = s.getsockname()[0]
        port = config.getPort()

        data['url'] = 'http://%s:%s' % (ip, port) + urllib.quote('/%s/%s' % (share_name, os.path.split(file_name)[-1]))
        data['duration'] = file_info['duration'] / 1000
        data['size'] = file_info['size']

        print data

        m = mind.getMind()
        m.completeDownloadRequest(data)

        self.sem.release()

