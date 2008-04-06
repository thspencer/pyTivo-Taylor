from plugins.video.video import Video, VideoDetails
import mind
import config

import xmpp

import threading
import urllib2
import os.path
import shutil
import os.path
import urllib
import xml.etree.ElementTree as ElementTree
import Queue

CLASS_NAME = 'WebVideo'


class WebVideo(Video):

    CONTENT_TYPE = 'x-not-for/tivo'

    def init(self):
        self.work_queue = Queue.Queue()
        self.download_thread_num = 1
        self.in_progress = {}
        self.in_progress_lock = threading.Lock()

        self.startXMPP()
        self.xmpp_cdsupdate()
        self.startWorkerThreads()

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

    def startWorkerThreads(self):
        for i in range(self.download_thread_num):
            t = threading.Thread(target=self.processDlRequest)
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

        self.in_progress_lock.acquire()
        try:
            for request in m.getDownloadRequests():
                if not request['bodyOfferId'] in self.in_progress:
                    self.in_progress[request['bodyOfferId']] = True
                    self.work_queue.put(request)
        finally:
            self.in_progress_lock.release()

    def processDlRequest(self):

        while True:
            data = self.work_queue.get()

            for share_name, settings in config.getShares():
                if settings['type'] == 'webvideo':
                    break


            path = settings['path']
            file_name = os.path.join(path, '%s-%s' % (data['bodyOfferId'] ,data['url'].split('/')[-1]))

            self.downloadFile(data['url'], file_name)

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

            self.in_progress_lock.acquire()
            try:
                del self.in_progress[data['bodyOfferId']]
            finally:
                self.in_progress_lock.release()


    def downloadFile(self, url, file_path):
        print 'downloading %s to %s' % (url, file_path)

        outfile = open(file_path, 'awb')
        size = os.path.getsize(file_path)
        r = urllib2.Request(url)
        if size:
            r.add_header('Range', 'bytes=%s-' % size)
        infile = urllib2.urlopen(r)
        shutil.copyfileobj(infile, outfile, 8192)

        print 'done downloading %s to %s' % (url, file_path)
