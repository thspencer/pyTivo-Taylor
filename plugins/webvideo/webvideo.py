from plugins.video.video import Video, VideoDetails
import mind
import config

import pyxmpp.jabber.client
from pyxmpp.all import *
from pyxmpp.streamtls import TLSSettings

import threading
import xml.etree.ElementTree as ElementTree

CLASS_NAME = 'WebVideo'

sem = threading.Semaphore(1)



class WebVideo(Video):
    
    CONTENT_TYPE = 'x-not-for/tivo'

    def init(self):
        c = XmppListener(self)
        c.connect()
        
        t = threading.Thread(target=c.loop)
        t.setDaemon(True)
        t.start()
        self.xmppCdsupdate()


    def xmppCdsupdate(self):
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

        sem.acquire()

        path = '/home/armooo/Videos/web'

        file_name = os.path.join(path, '%s-%s' % (data['bodyOfferId'] ,data['url'].split('/')[-1]))

        print 'downloading %s to %s' % (data['url'], file_name)

        outfile = open(file_name, 'wb')

        infile = urllib2.urlopen(data['url'])
        shutil.copyfileobj(infile, outfile)

        print 'done downloading %s to %s' % (data['url'], file_name)

        tsn = data['bodyId']
        file_info = VideoDetails()
        file_info.update(self.metadata_full(file_name, tsn))

        data['url'] = 'http://10.0.1.51:9032' + urllib.quote('/WebVideo/%s' % os.path.split(file_name)[-1])
        data['duration'] = file_info['duration'] / 1000
        data['size'] = file_info['size']

        print data

        m = mind.getMind()
        m.completeDownloadRequest(data)

        sem.release()

        
class XmppListener(Client):
    def __init__(self, web_video):
        m = mind.getMind()
        xmpp_info = m.getXMPPLoginInfo()

        Client.__init__(self,
            jid=JID(xmpp_info['username'] + '/pyTivo'), 
            password=config.getTivoPassword(), 
            server=xmpp_info['server'],
            port=xmpp_info['port'], 
            tls_settings=TLSSettings(verify_peer=False), 
            auth_methods = ('sasl:plain',),
        )

        self.web_video = web_video
        self.presence_list = xmpp_info['presence_list']

    def session_started(self):
        self.stream.set_message_handler(None, self.message)

        p = Presence()
        self.stream.send(p)
        for p in self.presence_list:
            print p
            p = Presence(to_jid=JID(p))
            self.stream.send(p)

    def message(self,stanza):
        xmpp_action = ElementTree.fromstring(stanza.get_body())

        method_name = 'xmpp_' + xmpp_action.findtext('action').lower()
        if not hasattr(self, method_name):
            return False
        
        method = getattr(self, method_name)
        method(xmpp_action)
        return True

    def xmpp_cdsupdate(self, xml):
        self.web_video.xmppCdsupdate()

