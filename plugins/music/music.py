import cgi
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib
from xml.sax.saxutils import escape

import mutagen
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
from Cheetah.Template import Template
from lrucache import LRUCache
import config
from plugin import EncodeUnicode, Plugin, quote, unquote
from plugins.video.transcode import kill

SCRIPTDIR = os.path.dirname(__file__)

CLASS_NAME = 'Music'

PLAYLISTS = ('.m3u', '.m3u8', '.ram', '.pls', '.b4s', '.wpl', '.asx',
             '.wax', '.wvx')

TRANSCODE = ('.mp4', '.m4a', '.flc', '.ogg', '.wma', '.aac', '.wav',
             '.aif', '.aiff', '.au', '.flac')

TAGNAMES = {'artist': ['\xa9ART', 'Author'],
            'title': ['\xa9nam', 'Title'],
            'album': ['\xa9alb', u'WM/AlbumTitle'],
            'date': ['\xa9day', u'WM/Year'],
            'genre': ['\xa9gen', u'WM/Genre']}

# Search strings for different playlist types
asxfile = re.compile('ref +href *= *"(.+)"', re.IGNORECASE).search
wplfile = re.compile('media +src *= *"(.+)"', re.IGNORECASE).search
b4sfile = re.compile('Playstring="file:(.+)"').search
plsfile = re.compile('[Ff]ile(\d+)=(.+)').match
plstitle = re.compile('[Tt]itle(\d+)=(.+)').match
plslength = re.compile('[Ll]ength(\d+)=(\d+)').match

# Duration -- parse from ffmpeg output
durre = re.compile(r'.*Duration: ([0-9]+):([0-9]+):([0-9]+)\.([0-9]+),').search

# Preload the templates
tfname = os.path.join(SCRIPTDIR, 'templates', 'container.tmpl')
tpname = os.path.join(SCRIPTDIR, 'templates', 'm3u.tmpl')
FOLDER_TEMPLATE = file(tfname, 'rb').read()
PLAYLIST_TEMPLATE = file(tpname, 'rb').read()

# XXX BIG HACK
# subprocess is broken for me on windows so super hack
def patchSubprocess():
    o = subprocess.Popen._make_inheritable

    def _make_inheritable(self, handle):
        if not handle: return subprocess.GetCurrentProcess()
        return o(self, handle)

    subprocess.Popen._make_inheritable = _make_inheritable

mswindows = (sys.platform == "win32")
if mswindows:
    patchSubprocess()
    
class FileData:
    def __init__(self, name, isdir):
        self.name = name
        self.isdir = isdir
        self.isplay = os.path.splitext(name)[1].lower() in PLAYLISTS
        self.title = ''
        self.duration = 0

class Music(Plugin):

    CONTENT_TYPE = 'x-container/tivo-music'

    AUDIO = 'audio'
    DIRECTORY = 'dir'
    PLAYLIST = 'play'

    media_data_cache = LRUCache(300)
    recurse_cache = LRUCache(5)
    dir_cache = LRUCache(10)

    def send_file(self, handler, path, query):
        seek = int(query.get('Seek', [0])[0])
        duration = int(query.get('Duration', [0])[0])

        fname = unicode(path, 'utf-8')

        ext = os.path.splitext(fname)[1].lower()
        needs_transcode = ext in TRANSCODE or seek or duration

        handler.send_response(200)
        handler.send_header('Content-Type', 'audio/mpeg')
        if not needs_transcode:
            fsize = os.path.getsize(fname)
            handler.send_header('Content-Length', fsize)
        handler.send_header('Connection', 'close')
        handler.end_headers()

        if needs_transcode:
            if mswindows:
                fname = fname.encode('iso8859-1')

            cmd = [config.get_bin('ffmpeg'), '-i', fname]
            if ext in ['.mp3', '.mp2']:
                cmd += ['-acodec', 'copy']
            else:
                cmd += ['-ab', '320k', '-ar', '44100']
            cmd += ['-f', 'mp3', '-']
            if seek:
                cmd[-1:] = ['-ss', '%.3f' % (seek / 1000.0), '-']
            if duration:
                cmd[-1:] = ['-t', '%.3f' % (duration / 1000.0), '-']

            ffmpeg = subprocess.Popen(cmd, bufsize=(64 * 1024),
                                      stdout=subprocess.PIPE)
            try:
                shutil.copyfileobj(ffmpeg.stdout, handler.wfile)
            except:
                kill(ffmpeg)
        else:
            f = open(fname, 'rb')
            try:
                shutil.copyfileobj(f, handler.wfile)
            except:
                pass
            f.close()

    def QueryContainer(self, handler, query):

        def AudioFileFilter(f, filter_type=None):
            ext = os.path.splitext(f)[1].lower()

            if ext in ('.mp3', '.mp2') or (ext in TRANSCODE and
                                           config.get_bin('ffmpeg')):
                return self.AUDIO
            else:
                file_type = False

                if not filter_type or filter_type.split('/')[0] != self.AUDIO:
                    if ext in PLAYLISTS:
                        file_type = self.PLAYLIST
                    elif os.path.isdir(f):
                        file_type = self.DIRECTORY

                return file_type

        def media_data(f):
            if f.name in self.media_data_cache:
                return self.media_data_cache[f.name]

            item = {}
            item['path'] = f.name
            item['part_path'] = f.name.replace(local_base_path, '', 1)
            item['name'] = os.path.basename(f.name)
            item['is_dir'] = f.isdir
            item['is_playlist'] = f.isplay
            item['params'] = 'No'

            if f.title:
                item['Title'] = f.title

            if f.duration > 0:
                item['Duration'] = f.duration

            if f.isdir or f.isplay or '://' in f.name:
                self.media_data_cache[f.name] = item
                return item

            # If the format is: (track #) Song name...
            #artist, album, track = f.name.split(os.path.sep)[-3:]
            #track = os.path.splitext(track)[0]
            #if track[0].isdigit:
            #    track = ' '.join(track.split(' ')[1:])

            #item['SongTitle'] = track
            #item['AlbumTitle'] = album
            #item['ArtistName'] = artist

            ext = os.path.splitext(f.name)[1].lower()
            fname = unicode(f.name, 'utf-8')

            try:
                # If the file is an mp3, let's load the EasyID3 interface
                if ext == '.mp3':
                    audioFile = MP3(fname, ID3=EasyID3)
                else:
                    # Otherwise, let mutagen figure it out
                    audioFile = mutagen.File(fname)

                if audioFile:
                    # Pull the length from the FileType, if present
                    if audioFile.info.length > 0:
                        item['Duration'] = int(audioFile.info.length * 1000)

                    # Grab our other tags, if present
                    def get_tag(tagname, d):
                        for tag in ([tagname] + TAGNAMES[tagname]):
                            try:
                                if tag in d:
                                    value = d[tag][0]
                                    if type(value) not in [str, unicode]:
                                        value = str(value)
                                    return value
                            except:
                                pass
                        return ''

                    artist = get_tag('artist', audioFile)
                    title = get_tag('title', audioFile)
                    if artist == 'Various Artists' and '/' in title:
                        artist, title = [x.strip() for x in title.split('/')]
                    item['ArtistName'] = artist
                    item['SongTitle'] = title
                    item['AlbumTitle'] = get_tag('album', audioFile)
                    item['AlbumYear'] = get_tag('date', audioFile)[:4]
                    item['MusicGenre'] = get_tag('genre', audioFile)
            except Exception, msg:
                print msg

            ffmpeg_path = config.get_bin('ffmpeg')
            if 'Duration' not in item and ffmpeg_path:
                if mswindows:
                    fname = fname.encode('iso8859-1')
                cmd = [ffmpeg_path, '-i', fname]
                ffmpeg = subprocess.Popen(cmd, stderr=subprocess.PIPE,
                                               stdout=subprocess.PIPE, 
                                               stdin=subprocess.PIPE)

                # wait 10 sec if ffmpeg is not back give up
                for i in xrange(200):
                    time.sleep(.05)
                    if not ffmpeg.poll() == None:
                        break

                if ffmpeg.poll() != None:
                    output = ffmpeg.stderr.read()
                    d = durre(output)
                    if d:
                        millisecs = ((int(d.group(1)) * 3600 +
                                      int(d.group(2)) * 60 +
                                      int(d.group(3))) * 1000 +
                                     int(d.group(4)) *
                                     (10 ** (3 - len(d.group(4)))))
                    else:
                        millisecs = 0
                    item['Duration'] = millisecs

            if 'Duration' in item and ffmpeg_path:
                item['params'] = 'Yes'

            self.media_data_cache[f.name] = item
            return item

        subcname = query['Container'][0]
        cname = subcname.split('/')[0]
        local_base_path = self.get_local_base_path(handler, query)

        if (not cname in handler.server.containers or
            not self.get_local_path(handler, query)):
            handler.send_error(404)
            return

        if os.path.splitext(subcname)[1].lower() in PLAYLISTS:
            t = Template(PLAYLIST_TEMPLATE, filter=EncodeUnicode)
            t.files, t.total, t.start = self.get_playlist(handler, query)
        else:
            t = Template(FOLDER_TEMPLATE, filter=EncodeUnicode)
            t.files, t.total, t.start = self.get_files(handler, query,
                                                       AudioFileFilter)
        t.files = map(media_data, t.files)
        t.container = cname
        t.name = subcname
        t.quote = quote
        t.escape = escape
        page = str(t)

        handler.send_response(200)
        handler.send_header('Content-Type', 'text/xml')
        handler.send_header('Content-Length', len(page))
        handler.send_header('Connection', 'close')
        handler.end_headers()
        handler.wfile.write(page)

    def parse_playlist(self, list_name, recurse):

        ext = os.path.splitext(list_name)[1].lower()

        try:
            url = list_name.index('http://')
            list_name = list_name[url:]
            list_file = urllib.urlopen(list_name)
        except:
            list_file = open(unicode(list_name, 'utf-8'))
            local_path = os.path.sep.join(list_name.split(os.path.sep)[:-1])

        if ext in ('.m3u', '.pls'):
            charset = 'iso-8859-1'
        else:
            charset = 'utf-8'

        if ext in ('.wpl', '.asx', '.wax', '.wvx', '.b4s'):
            playlist = []
            for line in list_file:
                line = unicode(line, charset).encode('utf-8')
                if ext == '.wpl':
                    s = wplfile(line)
                elif ext == '.b4s':
                    s = b4sfile(line)
                else:
                    s = asxfile(line)
                if s:
                    playlist.append(FileData(s.group(1), False))

        elif ext == '.pls':
            names, titles, lengths = {}, {}, {}
            for line in list_file:
                line = unicode(line, charset).encode('utf-8')
                s = plsfile(line)
                if s:
                    names[s.group(1)] = s.group(2)
                else:
                    s = plstitle(line)
                    if s:
                        titles[s.group(1)] = s.group(2)
                    else:
                        s = plslength(line)
                        if s:
                            lengths[s.group(1)] = int(s.group(2))
            playlist = []
            for key in names:
                f = FileData(names[key], False)
                if key in titles:
                    f.title = titles[key]
                if key in lengths:
                    f.duration = lengths[key]
                playlist.append(f)

        else: # ext == '.m3u' or '.m3u8' or '.ram'
            duration, title = 0, ''
            playlist = []
            for line in list_file:
                line = unicode(line.strip(), charset).encode('utf-8')
                if line:
                    if line.startswith('#EXTINF:'):
                        try:
                            duration, title = line[8:].split(',', 1)
                            duration = int(duration)
                        except ValueError:
                            duration = 0

                    elif not line.startswith('#'):
                        f = FileData(line, False)
                        f.title = title.strip()
                        f.duration = duration
                        playlist.append(f)
                        duration, title = 0, ''

        list_file.close()

        # Expand relative paths
        for i in xrange(len(playlist)):
            if not '://' in playlist[i].name:
                name = playlist[i].name
                if not os.path.isabs(name):
                    name = os.path.join(local_path, name)
                playlist[i].name = os.path.normpath(name)

        if recurse:
            newlist = []
            for i in playlist:
                if i.isplay:
                    newlist.extend(self.parse_playlist(i.name, recurse))
                else:
                    newlist.append(i)

            playlist = newlist

        return playlist

    def get_files(self, handler, query, filterFunction=None):

        class SortList:
            def __init__(self, files):
                self.files = files
                self.unsorted = True
                self.sortby = None
                self.last_start = 0
 
        def build_recursive_list(path, recurse=True):
            files = []
            path = unicode(path, 'utf-8')
            try:
                for f in os.listdir(path):
                    if f.startswith('.'):
                        continue
                    f = os.path.join(path, f)
                    isdir = os.path.isdir(f)
                    f = f.encode('utf-8')
                    if recurse and isdir:
                        files.extend(build_recursive_list(f))
                    else:
                        fd = FileData(f, isdir)
                        if recurse and fd.isplay:
                            files.extend(self.parse_playlist(f, recurse))
                        elif isdir or filterFunction(f, file_type):
                            files.append(fd)
            except:
                pass
            return files

        def dir_sort(x, y):
            if x.isdir == y.isdir:
                if x.isplay == y.isplay:
                    return name_sort(x, y)
                else:
                    return y.isplay - x.isplay
            else:
                return y.isdir - x.isdir

        def name_sort(x, y):
            return cmp(x.name, y.name)

        subcname = query['Container'][0]
        cname = subcname.split('/')[0]
        path = self.get_local_path(handler, query)

        file_type = query.get('Filter', [''])[0]

        recurse = query.get('Recurse', ['No'])[0] == 'Yes'

        filelist = []
        rc = self.recurse_cache
        dc = self.dir_cache
        if recurse:
            if path in rc:
                filelist = rc[path]
        else:
            updated = os.stat(unicode(path, 'utf-8'))[8]
            if path in dc and dc.mtime(path) >= updated:
                filelist = dc[path]
            for p in rc:
                if path.startswith(p) and rc.mtime(p) < updated:
                    del rc[p]

        if not filelist:
            filelist = SortList(build_recursive_list(path, recurse))

            if recurse:
                rc[path] = filelist
            else:
                dc[path] = filelist

        # Sort it
        seed = ''
        start = ''
        sortby = query.get('SortOrder', ['Normal'])[0] 
        if 'Random' in sortby:
            if 'RandomSeed' in query:
                seed = query['RandomSeed'][0]
                sortby += seed
            if 'RandomStart' in query:
                start = query['RandomStart'][0]
                sortby += start

        if filelist.unsorted or filelist.sortby != sortby:
            if 'Random' in sortby:
                self.random_lock.acquire()
                if seed:
                    random.seed(seed)
                random.shuffle(filelist.files)
                self.random_lock.release()
                if start:
                    local_base_path = self.get_local_base_path(handler, query)
                    start = unquote(start)
                    start = start.replace(os.path.sep + cname,
                                          local_base_path, 1)
                    filenames = [x.name for x in filelist.files]
                    try:
                        index = filenames.index(start)
                        i = filelist.files.pop(index)
                        filelist.files.insert(0, i)
                    except ValueError:
                        handler.server.logger.warning('Start not found: ' +
                                                      start)
            else:
                filelist.files.sort(dir_sort)

            filelist.sortby = sortby
            filelist.unsorted = False

        files = filelist.files[:]

        # Trim the list
        files, total, start = self.item_count(handler, query, cname, files,
                                              filelist.last_start)
        filelist.last_start = start
        return files, total, start

    def get_playlist(self, handler, query):
        subcname = query['Container'][0]
        cname = subcname.split('/')[0]

        try:
            url = subcname.index('http://')
            list_name = subcname[url:]
        except:
            list_name = self.get_local_path(handler, query)

        recurse = query.get('Recurse', ['No'])[0] == 'Yes'
        playlist = self.parse_playlist(list_name, recurse)

        # Shuffle?
        if 'Random' in query.get('SortOrder', ['Normal'])[0]:
            seed = query.get('RandomSeed', [''])[0]
            start = query.get('RandomStart', [''])[0]

            self.random_lock.acquire()
            if seed:
                random.seed(seed)
            random.shuffle(playlist)
            self.random_lock.release()
            if start:
                local_base_path = self.get_local_base_path(handler, query)
                start = unquote(start)
                start = start.replace(os.path.sep + cname,
                                      local_base_path, 1)
                filenames = [x.name for x in playlist]
                try:
                    index = filenames.index(start)
                    i = playlist.pop(index)
                    playlist.insert(0, i)
                except ValueError:
                    handler.server.logger.warning('Start not found: ' + start)

        # Trim the list
        return self.item_count(handler, query, cname, playlist)
