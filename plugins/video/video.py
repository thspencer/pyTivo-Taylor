import cgi
import logging
import os
import re
import subprocess
import time
import traceback
import urllib
import zlib
from UserDict import DictMixin
from datetime import datetime, timedelta
from xml.dom import minidom
from xml.sax.saxutils import escape

from Cheetah.Template import Template
from lrucache import LRUCache
import config
import mind
import qtfaststart
import transcode
from plugin import EncodeUnicode, Plugin, quote, tag_data, TRIBUNE_CR

logger = logging.getLogger('pyTivo.video.video')

SCRIPTDIR = os.path.dirname(__file__)

CLASS_NAME = 'Video'

# Preload the templates
def tmpl(name):
    return file(os.path.join(SCRIPTDIR, 'templates', name), 'rb').read()

CONTAINER_TEMPLATE = tmpl('container.tmpl')
TVBUS_TEMPLATE = tmpl('TvBus.tmpl')
XSL_TEMPLATE = tmpl('container.xsl')

extfile = os.path.join(SCRIPTDIR, 'video.ext')
try:
    assert(config.get_bin('ffmpeg'))
    extensions = file(extfile).read().split()
except:
    extensions = None

class Video(Plugin):

    CONTENT_TYPE = 'x-container/tivo-videos'

    tivo_cache = LRUCache(50)  # Metadata from .TiVo files

    def pre_cache(self, full_path):
        if Video.video_file_filter(self, full_path):
            transcode.supported_format(full_path)

    def video_file_filter(self, full_path, type=None):
        if os.path.isdir(full_path):
            return True
        if extensions:
            return os.path.splitext(full_path)[1].lower() in extensions
        else:
            return transcode.supported_format(full_path)

    def send_file(self, handler, path, query):
        mime = 'video/mpeg'
        tsn = handler.headers.getheader('tsn', '')

        is_tivo_file = (path[-5:].lower() == '.tivo')

        if is_tivo_file and transcode.tivo_compatible(path, tsn, mime)[0]:
            mime = 'video/x-tivo-mpeg'

        if 'Format' in query:
            mime = query['Format'][0]

        needs_tivodecode = (is_tivo_file and mime == 'video/mpeg')
        compatible = (not needs_tivodecode and
                      transcode.tivo_compatible(path, tsn, mime)[0])

        offset = handler.headers.getheader('Range')
        if offset:
            offset = int(offset[6:-1])  # "bytes=XXX-"

        if needs_tivodecode:
            valid = bool(config.get_bin('tivodecode') and
                         config.get_server('tivo_mak'))
        else:
            valid = True

        if valid and offset:
            valid = ((compatible and offset < os.stat(path).st_size) or
                     (not compatible and transcode.is_resumable(path, offset)))

        handler.send_response(206)
        handler.send_header('Content-Type', mime)
        handler.send_header('Connection', 'close')
        if compatible:
            handler.send_header('Content-Length',
                                os.stat(path).st_size - offset)
        else:
            handler.send_header('Transfer-Encoding', 'chunked')
        handler.end_headers()

        if valid:
            if compatible:
                logger.debug('%s is tivo compatible' % path)
                f = open(path, 'rb')
                try:
                    if mime == 'video/mp4':
                        qtfaststart.fast_start(f, handler.wfile, offset)
                    else:
                        if offset:
                            f.seek(offset)
                        while True:
                            block = f.read(512 * 1024)
                            if not block:
                                break
                            handler.wfile.write(block)
                except Exception, msg:
                    logger.info(msg)
                f.close()
            else:
                logger.debug('%s is not tivo compatible' % path)
                if offset:
                    transcode.resume_transfer(path, handler.wfile, offset)
                else:
                    transcode.transcode(False, path, handler.wfile, tsn)
        try:
            if not compatible:
                 handler.wfile.write('0\r\n\r\n')
            handler.wfile.flush()
        except Exception, msg:
            logger.info(msg)
        logger.debug("Finished outputing video")

    def __duration(self, full_path):
        return transcode.video_info(full_path)['millisecs']

    def __total_items(self, full_path):
        count = 0
        try:
            for f in os.listdir(full_path):
                if f.startswith('.'):
                    continue
                f = os.path.join(full_path, f)
                if os.path.isdir(f):
                    count += 1
                elif extensions:
                    if os.path.splitext(f)[1].lower() in extensions:
                        count += 1
                elif f in transcode.info_cache:
                    if transcode.supported_format(f):
                        count += 1
        except:
            pass
        return count

    def __est_size(self, full_path, tsn='', mime=''):
        # Size is estimated by taking audio and video bit rate adding 2%

        if transcode.tivo_compatible(full_path, tsn, mime)[0]:
            return int(os.stat(full_path).st_size)
        else:
            # Must be re-encoded
            if config.get_tsn('audio_codec', tsn) == None:
                audioBPS = config.getMaxAudioBR(tsn) * 1000
            else:
                audioBPS = config.strtod(config.getAudioBR(tsn))
            videoBPS = transcode.select_videostr(full_path, tsn)
            bitrate =  audioBPS + videoBPS
            return int((self.__duration(full_path) / 1000) *
                       (bitrate * 1.02 / 8))

    def getMetadataFromTxt(self, full_path):
        metadata = {}
        path, name = os.path.split(full_path)
        for metafile in [os.path.join(path, 'default.txt'), full_path + '.txt',
                         os.path.join(path, '.meta', name) + '.txt']:
            if os.path.exists(metafile):
                for line in file(metafile):
                    if line.strip().startswith('#') or not ':' in line:
                        continue
                    key, value = [x.strip() for x in line.split(':', 1)]
                    if key.startswith('v'):
                        if key in metadata:
                            metadata[key].append(value)
                        else:
                            metadata[key] = [value]
                    else:
                        metadata[key] = value
        return metadata

    def metadata_basic(self, full_path):
        base_path, title = os.path.split(full_path)
        mtime = os.stat(full_path).st_mtime
        if (mtime < 0):
            mtime = 0
        originalAirDate = datetime.fromtimestamp(mtime)

        metadata = {'title': '.'.join(title.split('.')[:-1]),
                    'originalAirDate': originalAirDate.isoformat()}

        metadata.update(self.getMetadataFromTxt(full_path))

        return metadata

    def metadata_tivo(self, full_path):
        if full_path in self.tivo_cache:
            return self.tivo_cache[full_path]

        metadata = {}

        tdcat_path = config.get_bin('tdcat')
        tivo_mak = config.get_server('tivo_mak')
        if tdcat_path and tivo_mak:
            tcmd = [tdcat_path, '-m', tivo_mak, '-2', full_path]
            tdcat = subprocess.Popen(tcmd, stdout=subprocess.PIPE)
            xmldoc = minidom.parse(tdcat.stdout)
            showing = xmldoc.getElementsByTagName('showing')[0]

            items = {'description': 'program/description',
                     'title': 'program/title',
                     'episodeTitle': 'program/episodeTitle',
                     'episodeNumber': 'program/episodeNumber',
                     'seriesTitle': 'program/series/seriesTitle',
                     'originalAirDate': 'program/originalAirDate',
                     'isEpisode': 'program/isEpisode',
                     'movieYear': 'program/movieYear',
                     'showingBits': 'showingBits',
                     'partCount': 'partCount',
                     'partIndex': 'partIndex'}

            for item in items.keys():
                data = tag_data(showing, item)
                if data:
                    metadata[item] = data

            if 'description' in metadata:
                desc = metadata['description']
                metadata['description'] = desc.replace(TRIBUNE_CR, '')

            self.tivo_cache[full_path] = metadata

        return metadata

    def metadata_full(self, full_path, tsn='', mime=''):
        metadata = {}
        vInfo = transcode.video_info(full_path)

        if config.getDebug():
            compatible, reason = transcode.tivo_compatible(full_path, tsn, mime)
            if compatible:
                transcode_options = {}
            else:
                transcode_options = transcode.transcode(True, full_path,
                                                        '', tsn)
            metadata['vHost'] = (
                ['TRANSCODE=%s, %s' % (['YES', 'NO'][compatible], reason)] +
                ['SOURCE INFO: '] +
                ["%s=%s" % (k, v)
                 for k, v in sorted(vInfo.items(), reverse=True)] +
                ['TRANSCODE OPTIONS: '] +
                ["%s" % (v) for k, v in transcode_options.items()] +
                ['SOURCE FILE: ', os.path.split(full_path)[1]]
            )

        if ((int(vInfo['vHeight']) >= 720 and
             config.getTivoHeight >= 720) or
            (int(vInfo['vWidth']) >= 1280 and
             config.getTivoWidth >= 1280)):
            metadata['showingBits'] = '4096'

        metadata.update(self.metadata_basic(full_path))
        if full_path[-5:].lower() == '.tivo':
            metadata.update(self.metadata_tivo(full_path))

        now = datetime.utcnow()
        duration = self.__duration(full_path)
        duration_delta = timedelta(milliseconds = duration)
        min = duration_delta.seconds / 60
        sec = duration_delta.seconds % 60
        hours = min / 60
        min = min % 60

        metadata.update({'time': now.isoformat(),
                         'startTime': now.isoformat(),
                         'stopTime': (now + duration_delta).isoformat(),
                         'size': self.__est_size(full_path, tsn, mime),
                         'duration': duration,
                         'iso_duration': ('P%sDT%sH%sM%sS' % 
                              (duration_delta.days, hours, min, sec))})

        return metadata

    def QueryContainer(self, handler, query):
        tsn = handler.headers.getheader('tsn', '')
        subcname = query['Container'][0]
        cname = subcname.split('/')[0]

        if (not cname in handler.server.containers or
            not self.get_local_path(handler, query)):
            handler.send_error(404)
            return

        container = handler.server.containers[cname]
        precache = container.get('precache', 'False').lower() == 'true'
        force_alpha = container.get('force_alpha', 'False').lower() == 'true'

        files, total, start = self.get_files(handler, query,
                                             self.video_file_filter,
                                             force_alpha)

        videos = []
        local_base_path = self.get_local_base_path(handler, query)
        for f in files:
            mtime = datetime.fromtimestamp(f.mdate)
            video = VideoDetails()
            video['captureDate'] = hex(int(time.mktime(mtime.timetuple())))
            video['name'] = os.path.split(f.name)[1]
            video['path'] = f.name
            video['part_path'] = f.name.replace(local_base_path, '', 1)
            if not video['part_path'].startswith(os.path.sep):
                video['part_path'] = os.path.sep + video['part_path']
            video['title'] = os.path.split(f.name)[1]
            video['is_dir'] = f.isdir
            if video['is_dir']:
                video['small_path'] = subcname + '/' + video['name']
                video['total_items'] = self.__total_items(f.name)
            else:
                if precache or len(files) == 1 or f.name in transcode.info_cache:
                    video['valid'] = transcode.supported_format(f.name)
                    if video['valid']:
                        video.update(self.metadata_full(f.name, tsn))
                else:
                    video['valid'] = True
                    video.update(self.metadata_basic(f.name))

            videos.append(video)

        t = Template(CONTAINER_TEMPLATE, filter=EncodeUnicode)
        t.container = cname
        t.name = subcname
        t.total = total
        t.start = start
        t.videos = videos
        t.quote = quote
        t.escape = escape
        t.crc = zlib.crc32
        t.guid = config.getGUID()
        t.tivos = config.tivos
        t.tivo_names = config.tivo_names
        handler.send_response(200)
        handler.send_header('Content-Type', 'text/xml')
        handler.end_headers()
        handler.wfile.write(t)

    def TVBusQuery(self, handler, query):
        tsn = handler.headers.getheader('tsn', '')
        f = query['File'][0]
        path = self.get_local_path(handler, query)
        file_path = path + os.path.normpath(f)

        file_info = VideoDetails()
        file_info['valid'] = transcode.supported_format(file_path)
        if file_info['valid']:
            file_info.update(self.metadata_full(file_path, tsn))

        t = Template(TVBUS_TEMPLATE, filter=EncodeUnicode)
        t.video = file_info
        t.escape = escape
        handler.send_response(200)
        handler.send_header('Content-Type', 'text/xml')
        handler.end_headers()
        handler.wfile.write(t)

    def XSL(self, handler, query):
        handler.send_response(200)
        handler.send_header('Content-Type', 'text/xml')
        handler.end_headers()
        handler.wfile.write(XSL_TEMPLATE)

    def Push(self, handler, query):
        tsn = query['tsn'][0]
        for key in config.tivo_names:
            if config.tivo_names[key] == tsn:
                tsn = key
                break

        container = quote(query['Container'][0].split('/')[0])
        ip = config.get_ip()
        port = config.getPort()

        baseurl = 'http://%s:%s' % (ip, port)
        if config.getIsExternal(tsn):
            exturl = config.get_server('externalurl')
            if exturl:
                baseurl = exturl
            else:
                ip = self.readip()
                baseurl = 'http://%s:%s' % (ip, port)
 
        path = self.get_local_base_path(handler, query)

        for f in query.get('File', []):
            file_path = path + os.path.normpath(f)

            file_info = VideoDetails()
            file_info['valid'] = transcode.supported_format(file_path)

            mime = 'video/mpeg'
            if config.isHDtivo(tsn):
                for m in ['video/mp4', 'video/bif']:
                    if transcode.tivo_compatible(file_path, tsn, m)[0]:
                        mime = m
                        break

            if file_info['valid']:
                file_info.update(self.metadata_full(file_path, tsn, mime))

            url = baseurl + '/%s%s' % (container, quote(f))

            title = file_info['seriesTitle']
            if not title:
                title = file_info['title']

            source = file_info['seriesId']
            if not source:
                source = title

            subtitle = file_info['episodeTitle']
            logger.debug('Pushing ' + url)
            try:
                m = mind.getMind(tsn)
                m.pushVideo(
                    tsn = tsn,
                    url = url,
                    description = file_info['description'],
                    duration = file_info['duration'] / 1000,
                    size = file_info['size'],
                    title = title,
                    subtitle = subtitle,
                    source = source,
                    mime = mime)
            except Exception, e:
                handler.send_response(500)
                handler.end_headers()
                handler.wfile.write('%s\n\n%s' % (e, traceback.format_exc() ))
                raise

        referer = handler.headers.getheader('Referer')
        handler.send_response(302)
        handler.send_header('Location', referer)
        handler.end_headers()

    def readip(self):
        """ returns your external IP address by querying dyndns.org """
        f = urllib.urlopen('http://checkip.dyndns.org/')
        s = f.read()
        m = re.search('([\d]*\.[\d]*\.[\d]*\.[\d]*)', s)
        return m.group(0)

class VideoDetails(DictMixin):

    def __init__(self, d=None):
        if d:
            self.d = d
        else:
            self.d = {}

    def __getitem__(self, key):
        if key not in self.d:
            self.d[key] = self.default(key)
        return self.d[key]

    def __contains__(self, key):
        return True

    def __setitem__(self, key, value):
        self.d[key] = value

    def __delitem__(self):
        del self.d[key]

    def keys(self):
        return self.d.keys()

    def __iter__(self):
        return self.d.__iter__()

    def iteritems(self):
        return self.d.iteritems()

    def default(self, key):
        defaults = {
            'showingBits' : '0',
            'episodeNumber' : '0',
            'displayMajorNumber' : '0',
            'displayMinorNumber' : '0',
            'isEpisode' : 'true',
            'colorCode' : ('COLOR', '4'),
            'showType' : ('SERIES', '5'),
            'tvRating' : ('NR', '7')
        }
        if key in defaults:
            return defaults[key]
        elif key.startswith('v'):
            return []
        else:
            return ''
