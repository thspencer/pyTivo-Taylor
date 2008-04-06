import cookielib
import urllib2
import urllib
import struct
import httplib
import time
import warnings
import itertools
import config

try:
    import xml.etree.ElementTree as ElementTree
except ImportError:
    try:
        import elementtree.ElementTree as ElementTree
    except ImportError:
        warnings.warn('Python 2.5 or higher or elementtree is needed to use the TivoPush')

if 'ElementTree' not in locals():

    class Mind:
        def __init__(self, *arg, **karg):
            raise Exception('Python 2.5 or higher or elementtree is needed to use the TivoPush')

else:

    class Mind:
        def __init__(self, username, password, debug=False):
            self.__username = username
            self.__password = password

            self.__debug = debug

            self.__cj = cookielib.CookieJar()
            self.__opener = urllib2.build_opener(urllib2.HTTPSHandler(debuglevel=1), urllib2.HTTPCookieProcessor(self.__cj))

            self.__login()

            if not self.__pcBodySearch():
                self.__pcBodyStore('pyTivo', True)

        def pushVideo(self, tsn, url, description, duration, size, title, subtitle):
            data = {
                'bodyId' : 'tsn:' + tsn,
                'description' : description,
                'duration' : duration,
                'encodingType' : 'mpeg2ProgramStream',
                'partnerId' : 'tivo:pt.3187',
                'pcBodyId' : pc_body_id,
                'publishDate' : time.strftime('%Y-%m-%d %H:%M%S', time.gmtime()),
                'size' : size,
                'source' : 'file:/C%3A%2FDocuments%20and%20Settings%2FStephanie%2FDesktop%2FVideo',
                'state' : 'complete',
                'subtitle' : subtitle,
                'title' : title,
                'url' : url,
            }

            # It looks like tivo only supports one pc per house
            pc_body_id = self.__pcBodySearch()[0]
            offer_id, content_id = self.__bodyOfferModify(data)
            self.__subscribe(offer_id, content_id, tsn)

        def getDownloadRequests(self):
            NEEDED_VALUES = [
                'bodyId',
                'bodyOfferId',
                'description',
                'partnerId',
                'pcBodyId',
                'publishDate',
                'source',
                'state',
                'subscriptionId',
                'subtitle',
                'title',
                'url',
            ]

            # It looks like tivo only supports one pc per house
            pc_body_id = self.__pcBodySearch()[0]

            requests = []
            offer_list = self.__bodyOfferSchedule(pc_body_id)

            for offer in offer_list.findall('bodyOffer'):
                d = {}
                if offer.findtext('state') != 'scheduled':
                    continue

                for n in NEEDED_VALUES:
                    d[n] = offer.findtext(n)
                requests.append(d)

            return requests

        def completeDownloadRequest(self, request):
            request['encodingType'] = 'mpeg2ProgramStream'
            request['state'] = 'complete'
            request['type'] = 'bodyOfferModify'
            request['updateDate'] = time.strftime('%Y-%m-%d %H:%M%S', time.gmtime())

            offer_id, content_id = self.__bodyOfferModify(request)
            self.__subscribe(offer_id, content_id, request['bodyId'][4:])


        def getXMPPLoginInfo(self):
            # It looks like tivo only supports one pc per house
            pc_body_id = self.__pcBodySearch()[0]

            xml = self.__bodyXmppInfoGet(pc_body_id)

            results = {}
            results['server'] = xml.findtext('server')
            results['port'] = int(xml.findtext('port'))
            results['username'] = xml.findtext('xmppId')

            for sendPresence in xml.findall('sendPresence'):
                results.setdefault('presence_list', []).append(sendPresence.text)

            return results

        def __log(self, message):
            if self.__debug:
                print message
                print

        def __login(self):

            data = {
                'cams_security_domain' : 'tivocom',
                'cams_login_config' : 'http',
                'cams_cb_username' : self.__username,
                'cams_cb_password' : self.__password,
                'cams_original_url' : '/mind/mind7?type=infoGet'
            }

            r =  urllib2.Request(
                'https://mind.tivo.com:8181/mind/login',
                urllib.urlencode(data)
            )
            try:
                result = self.__opener.open(r)
            except:
                pass

            self.__log('__login\n%s' % (data))

        def __bodyOfferModify(self, data):
            """Create an offer"""
            r = urllib2.Request(
                'https://mind.tivo.com:8181/mind/mind7?type=bodyOfferModify&bodyId=' + data['bodyId'],
                dictcode(data),
                {'Content-Type' : 'x-tivo/dict-binary'}
            )
            result = self.__opener.open(r)

            xml = ElementTree.parse(result).find('.')

            self.__log('__bodyOfferModify\n%s\n\n%sg' % (data, ElementTree.tostring(xml)))

            if xml.findtext('state') != 'complete':
                raise Exception(ElementTree.tostring(xml))

            offer_id = xml.findtext('offerId')
            content_id = offer_id.replace('of','ct')

            return offer_id, content_id


        def __subscribe(self, offer_id, content_id, tsn):
            """Push the offer to the tivo"""
            data =  {
                'bodyId' : 'tsn:' + tsn,
                'idSetSource' : {
                    'contentId': content_id,
                    'offerId' : offer_id,
                    'type' : 'singleOfferSource',
                },
                'title' : 'pcBodySubscription',
                'uiType' : 'cds',
            }

            r = urllib2.Request(
                'https://mind.tivo.com:8181/mind/mind7?type=subscribe&bodyId=tsn:' + tsn,
                dictcode(data),
                {'Content-Type' : 'x-tivo/dict-binary'}
            )
            result = self.__opener.open(r)

            xml = ElementTree.parse(result).find('.')

            self.__log('__subscribe\n%s\n\n%sg' % (data, ElementTree.tostring(xml)))

            return xml

        def __bodyOfferSchedule(self, pc_body_id):
            """Get pending stuff for this pc"""

            data = {'pcBodyId' : pc_body_id,}
            r = urllib2.Request(
                'https://mind.tivo.com:8181/mind/mind7?type=bodyOfferSchedule',
                dictcode(data),
                {'Content-Type' : 'x-tivo/dict-binary'}
            )
            result = self.__opener.open(r)

            xml = ElementTree.parse(result).find('.')

            self.__log('bodyOfferSchedule\n%s\n\n%sg' % (data, ElementTree.tostring(xml)))

            return xml

        def __pcBodySearch(self):
            """Find PCS"""

            data = {}
            r = urllib2.Request(
                'https://mind.tivo.com:8181/mind/mind7?type=pcBodySearch',
                dictcode(data),
                {'Content-Type' : 'x-tivo/dict-binary'}
            )
            result = self.__opener.open(r)

            xml = ElementTree.parse(result).find('.')


            self.__log('__pcBodySearch\n%s\n\n%sg' % (data, ElementTree.tostring(xml)))

            return [id.text for id in xml.findall('pcBody/pcBodyId')]

        def __collectionIdSearch(self, url):
            """Find collection ids"""

            data = {'url' : url}
            r = urllib2.Request(
                'https://mind.tivo.com:8181/mind/mind7?type=collectionIdSearch',
                dictcode(data),
                {'Content-Type' : 'x-tivo/dict-binary'}
            )
            result = self.__opener.open(r)

            xml = ElementTree.parse( result ).find('.')
            collection_id = xml.findtext('collectionId')

            self.__log('__collectionIdSearch\n%s\n\n%sg' % (data, ElementTree.tostring(xml)))

            return collection_id

        def __pcBodyStore(self, name, replace=False):
            """Setup a new PC"""

            data = {
                'name' : name,
                'replaceExisting' : str(replace).lower(),
            }

            r = urllib2.Request(
                'https://mind.tivo.com:8181/mind/mind7?type=pcBodyStore',
                dictcode(data),
                {'Content-Type' : 'x-tivo/dict-binary'}
            )
            result = self.__opener.open(r)

            xml = ElementTree.parse(result).find('.')

            self.__log('__pcBodySearch\n%s\n\n%s' % (data, ElementTree.tostring(xml)))

            return xml

        def __bodyXmppInfoGet(self, body_id):

            data = {
                'bodyId' : body_id,
            }

            r = urllib2.Request(
                'https://mind.tivo.com:8181/mind/mind7?type=bodyXmppInfoGet&bodyId=' + body_id,
                dictcode(data),
                {'Content-Type' : 'x-tivo/dict-binary'}
            )

            result = self.__opener.open(r)

            xml = ElementTree.parse(result).find('.')

            self.__log('__bodyXmppInfoGe\n%s\n\n%s' % (data, ElementTree.tostring(xml)))

            return xml


    def dictcode(d):
        """Helper to create x-tivo/dict-binary"""
        output = []

        keys = [str(k) for k in d]
        keys.sort()

        for k in keys:
            v = d[k]

            output.append( varint( len(k) ) )
            output.append( k )

            if isinstance(v, dict):
                output.append( struct.pack('>B', 0x02) )
                output.append( dictcode(v) )

            else:
                v = unicode(v).encode('utf-8')
                output.append( struct.pack('>B', 0x01) )
                output.append( varint( len(v) ) )
                output.append( v )

            output.append( struct.pack('>B', 0x00) )

        output.append( struct.pack('>B', 0x80) )

        return ''.join(output)

    def varint(i):
        import sys

        bits = []
        while i:
            bits.append(i & 0x01)
            i = i  >> 1

        if not bits:
            output = [0]
        else:
            output = []

        while bits:
            byte = 0
            mybits = bits[:7]
            del bits[:7]

            for bit, p in zip(mybits, itertools.count()):
                byte += bit * (2 ** p)

            output.append(byte)

        output[-1] = output[-1] | 0x80
        return ''.join([chr(b) for b in output])


def getMind():
    username = config.getTivoUsername()
    password = config.getTivoPassword()

    if not username or not password:
       raise Exception("tivo_username and tivo_password required")

    m = Mind(username, password, True)

    return m

