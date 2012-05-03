import cookielib
import logging
import sys
import time
import urllib2
import urllib
import warnings

import config
import metadata

try:
    import xml.etree.ElementTree as ElementTree
except ImportError:
    try:
        import elementtree.ElementTree as ElementTree
    except ImportError:
        warnings.warn('Python 2.5 or higher or elementtree is ' +
                      'needed to use the TivoPush')

if 'ElementTree' not in locals():

    class Mind:
        def __init__(self, *arg, **karg):
            raise Exception('Python 2.5 or higher or elementtree is ' +
                            'needed to use the TivoPush')

else:

    class Mind:
        def __init__(self, username, password, tsn):
            self.__logger = logging.getLogger('pyTivo.mind')
            self.__username = username
            self.__password = password
            self.__mind = config.get_mind(tsn)

            cj = cookielib.CookieJar()
            cp = urllib2.HTTPCookieProcessor(cj)
            self.__opener = urllib2.build_opener(cp)

            self.__login()

        def pushVideo(self, tsn, url, description, duration, size,
                      title, subtitle, source='', mime='video/mpeg',
                      tvrating=None):
            # It looks like tivo only supports one pc per house
            pc_body_id = self.__pcBodySearch()

            if not source:
                source = title

            data = {
                'bodyId': 'tsn:' + tsn,
                'description': description,
                'duration': duration,
                'partnerId': 'tivo:pt.3187',
                'pcBodyId': pc_body_id,
                'publishDate': time.strftime('%Y-%m-%d %H:%M%S', time.gmtime()),
                'size': size,
                'source': source,
                'state': 'complete',
                'title': title
            }

            rating = metadata.get_tv(tvrating)
            if rating:
                data['tvRating'] = rating.lower()

            mtypes = {'video/mp4': 'avcL41MP4', 'video/bif': 'vc1ApL3'}
            data['encodingType'] = mtypes.get(mime, 'mpeg2ProgramStream')

            data['url'] = url + '?Format=' + mime

            if subtitle:
                data['subtitle'] = subtitle

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
            pc_body_id = self.__pcBodySearch()

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

        def completeDownloadRequest(self, request, status, mime='video/mpeg'):
            if status:
                mtypes = {'video/mp4': 'avcL41MP4', 'video/bif': 'vc1ApL3'}
                request['encodingType'] = mtypes.get(mime, 'mpeg2ProgramStream')
                request['url'] += '?Format=' + mime
                request['state'] = 'complete'
            else:
                request['state'] = 'cancelled'
                request['cancellationReason'] = 'httpFileNotFound'
            request['type'] = 'bodyOfferModify'
            request['updateDate'] = time.strftime('%Y-%m-%d %H:%M%S',
                                                  time.gmtime())

            offer_id, content_id = self.__bodyOfferModify(request)
            if status:
                self.__subscribe(offer_id, content_id, request['bodyId'][4:])

        def getXMPPLoginInfo(self):
            # It looks like tivo only supports one pc per house
            pc_body_id = self.__pcBodySearch()

            xml = self.__bodyXmppInfoGet(pc_body_id)

            results = {
                'server': xml.findtext('server'),
                'port': int(xml.findtext('port')),
                'username': xml.findtext('xmppId')
            }

            for sendPresence in xml.findall('sendPresence'):
                results.setdefault('presence_list',[]).append(sendPresence.text)

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
                'https://%s/mind/login' % self.__mind,
                urllib.urlencode(data)
            )
            try:
                result = self.__opener.open(r)
            except:
                pass

            self.__logger.debug('__login\n%s' % (data))

        def __dict_request(self, data, req):
            r = urllib2.Request(
                'https://%s/mind/mind7?type=%s' % (self.__mind, req),
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

            offer_id = xml.findtext('offerId')
            if offer_id:
                content_id = offer_id.replace('of','ct')

                return offer_id, content_id
            else:
                raise Exception(ElementTree.tostring(xml))

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
            id = xml.findtext('.//pcBodyId')
            curName = xml.findtext('.//name')
            ourName = 'pyTivo'

            if not id or curName != ourName:
                xml = self.__pcBodyStore(ourName, True)
                id = xml.findtext('.//pcBodyId')

            return id

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
                if type(v) == str:
                    try:
                        v = v.decode('utf8')
                    except:
                        if sys.platform == 'darwin':
                            v = v.decode('macroman')
                        else:
                            v = v.decode('iso8859-1')
                elif type(v) != unicode:
                    v = str(v)
                v = v.encode('utf-8')
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

def getMind(tsn=None):
    username = config.get_tsn('tivo_username', tsn)
    password = config.get_tsn('tivo_password', tsn)

    if not username or not password:
       raise Exception("tivo_username and tivo_password required")

    return Mind(username, password, tsn)
