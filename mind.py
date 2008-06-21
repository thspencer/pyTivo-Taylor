import cookielib
import urllib2
import urllib
import time
import warnings
import config
import logging

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
        def __init__(self, username, password):
            self.__logger = logging.getLogger('pyTivo.mind')
            self.__username = username
            self.__password = password

            self.__cj = cookielib.CookieJar()
            self.__opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(self.__cj))

            self.__login()

            if not self.__pcBodySearch():
                self.__pcBodyStore('pyTivo', True)

        def pushVideo(self, tsn, url, description, duration, size, title, subtitle):
            # It looks like tivo only supports one pc per house
            pc_body_id = self.__pcBodySearch()[0]

            data = {
                'bodyId': 'tsn:' + tsn,
                'description': description,
                'duration': duration,
                'encodingType': 'mpeg2ProgramStream',
                'partnerId': 'tivo:pt.3187',
                'pcBodyId': pc_body_id,
                'publishDate': time.strftime('%Y-%m-%d %H:%M%S', time.gmtime()),
                'size': size,
                'source': 'file:/C%3A%2FDocuments%20and%20Settings%2FStephanie%2FDesktop%2FVideo',
                'state': 'complete',
                'subtitle': subtitle,
                'title': title,
                'url': url
            }

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
                'url'
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

        def __login(self):

            data = {
                'cams_security_domain': 'tivocom',
                'cams_login_config': 'http',
                'cams_cb_username': self.__username,
                'cams_cb_password': self.__password,
                'cams_original_url': '/mind/mind7?type=infoGet'
            }

            r =  urllib2.Request(
                'https://mind.tivo.com:8181/mind/login',
                urllib.urlencode(data)
            )
            try:
                result = self.__opener.open(r)
            except:
                pass

            self.__logger.debug('__login\n%s' % (data))

        def __dict_request(self, data, req):
            r = urllib2.Request(
                'https://mind.tivo.com:8181/mind/mind7?type=' + req,
                dictcode(data),
                {'Content-Type': 'x-tivo/dict-binary'}
            )
            result = self.__opener.open(r)

            xml = ElementTree.parse(result).find('.')

            self.__logger.debug('%s\n%s\n\n%sg' % (req, data,
                                ElementTree.tostring(xml)))
            return xml

        def __bodyOfferModify(self, data):
            """Create an offer"""

            xml = self.__dict_request(data, 'bodyOfferModify&bodyId=' +
                                      data['bodyId'])

            if xml.findtext('state') != 'complete':
                raise Exception(ElementTree.tostring(xml))

            offer_id = xml.findtext('offerId')
            content_id = offer_id.replace('of','ct')

            return offer_id, content_id


        def __subscribe(self, offer_id, content_id, tsn):
            """Push the offer to the tivo"""
            data = {
                'bodyId': 'tsn:' + tsn,
                'idSetSource': {
                    'contentId': content_id,
                    'offerId': offer_id,
                    'type': 'singleOfferSource'
                },
                'title': 'pcBodySubscription',
                'uiType': 'cds'
            }

            return self.__dict_request(data, 'subscribe&bodyId=tsn:' + tsn)

        def __bodyOfferSchedule(self, pc_body_id):
            """Get pending stuff for this pc"""

            data = {'pcBodyId': pc_body_id}
            return self.__dict_request(data, 'bodyOfferSchedule')

        def __pcBodySearch(self):
            """Find PCS"""

            xml = self.__dict_request({}, 'pcBodySearch')

            return [id.text for id in xml.findall('pcBody/pcBodyId')]

        def __collectionIdSearch(self, url):
            """Find collection ids"""

            xml = self.__dict_request({'url': url}, 'collectionIdSearch')
            return xml.findtext('collectionId')

        def __pcBodyStore(self, name, replace=False):
            """Setup a new PC"""

            data = {
                'name': name,
                'replaceExisting': str(replace).lower()
            }

            return self.__dict_request(data, 'pcBodyStore')

        def __bodyXmppInfoGet(self, body_id):

            return self.__dict_request({'bodyId': body_id},
                                       'bodyXmppInfoGet&bodyId=' + body_id)


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
                output.append( chr(2) )
                output.append( dictcode(v) )

            else:
                v = unicode(v).encode('utf-8')
                output.append( chr(1) )
                output.append( varint( len(v) ) )
                output.append( v )

            output.append( chr(0) )

        output.append( chr(0x80) )

        return ''.join(output)

    def varint(i):
        output = []
        while i > 0x7f:
            output.append( chr(i & 0x7f) )
            i >>= 7
        output.append( chr(i | 0x80) )
        return ''.join(output)

def getMind():
    username = config.getTivoUsername()
    password = config.getTivoPassword()

    if not username or not password:
       raise Exception("tivo_username and tivo_password required")

    return Mind(username, password)
