#!/usr/bin/env python

import os
import subprocess
from datetime import datetime
from xml.dom import minidom

import mutagen
from lrucache import LRUCache

import config

# Something to strip
TRIBUNE_CR = ' Copyright Tribune Media Services, Inc.'

tivo_cache = LRUCache(50)
mp4_cache = LRUCache(50)

def tag_data(element, tag):
    for name in tag.split('/'):
        new_element = element.getElementsByTagName(name)
        if not new_element:
            return ''
        element = new_element[0]
    if not element.firstChild:
        return ''
    return element.firstChild.data

def _vtag_data(element, tag):
    for name in tag.split('/'):
        new_element = element.getElementsByTagName(name)
        if not new_element:
            return []
        element = new_element[0]
    elements = element.getElementsByTagName('element')
    return [x.firstChild.data for x in elements if x.firstChild]

def _tag_value(element, tag):
    item = element.getElementsByTagName(tag)
    if item:
        value = item[0].attributes['value'].value
        name = item[0].firstChild.data
        return name[0] + value[0]

def from_moov(full_path):
    if full_path in mp4_cache:
        return mp4_cache[full_path]

    metadata = {}
    len_desc = 0

    try:
        mp4meta = mutagen.File(full_path)
        assert(mp4meta)
    except:
        mp4_cache[full_path] = {}
        return {}

    for key, value in mp4meta.items():
        # The following 1-to-1 correspondence of atoms to pyTivo
        # variables is TV-biased
        keys = {'tvnn': 'callsign', 'tven': 'episodeNumber',
                'tvsh': 'seriesTitle'}
        if type(value) == list:
            value = value[0]
        if key == 'stik':
            metadata['isEpisode'] = ['false', 'true'][value == 'TV Show']
        elif key in keys:
            metadata[keys[key]] = value
        # These keys begin with the copyright symbol \xA9
        elif key == '\xa9day':
            if len(value) == 4:
                value += '-01-01T16:00:00Z'
            metadata['originalAirDate'] = value
            #metadata['time'] = value
        elif key in ['\xa9gen', 'gnre']:
            for k in ('vProgramGenre', 'vSeriesGenre'):
                if k in metadata:
                    metadata[k].append(value)
                else:
                    metadata[k] = [value]
        elif key == '\xa9nam':
            if 'tvsh' in mp4meta:
                metadata['episodeTitle'] = value
            else:
                metadata['title'] = value

        # Description in desc, cmt, and/or ldes tags. Keep the longest.
        elif key in ['desc', '\xa9cmt', 'ldes'] and len(value) > len_desc:
            metadata['description'] = value
            len_desc = len(value)

        # A common custom "reverse DNS format" tag
        # Possible TV values: TV-Y7 TV-Y TV-G TV-PG TV-14 TV-MA Unrated
        # Possible MPAA values: G PG PG-13 R NC-17 Unrated
        elif (key == '----:com.apple.iTunes:iTunEXTC' and
              ('us-tv' in value or 'mpaa' in value)):
            ratings = {'TV-Y7': 'x1', 'TV-Y': 'x2', 'TV-G': 'x3',
                       'TV-PG': 'x4', 'TV-14': 'x5', 'TV-MA': 'x6',
                       'Unrated': 'x7', 'G': 'G1', 'PG': 'P2',
                       'PG-13': 'P3', 'R': 'R4', 'NC-17': 'N6'}
            rating = value.split("|")[1]
            if rating in ratings:
                if 'us-tv' in value:
                    metadata['tvRating'] = ratings[rating]
                elif 'mpaa' in value:
                    metadata['mpaaRating'] = ratings[rating]

        # Actors, directors, producers, AND screenwriters may be in a long
        # embedded XML plist, with key '----' and rDNS 'iTunMOVI'. Ughh!

    mp4_cache[full_path] = metadata
    return metadata

def from_text(full_path):
    metadata = {}
    path, name = os.path.split(full_path)
    title, ext = os.path.splitext(name)
    for metafile in [os.path.join(path, 'default.txt'), full_path + '.txt',
                     os.path.join(path, '.meta', name) + '.txt',
                     os.path.join(path, title) + '.properties']:
        if os.path.exists(metafile):
            sep = ':='[metafile.endswith('.properties')]
            for line in file(metafile):
                if line.strip().startswith('#') or not sep in line:
                    continue
                key, value = [x.strip() for x in line.split(sep, 1)]
                if key.startswith('v'):
                    if key in metadata:
                        metadata[key].append(value)
                    else:
                        metadata[key] = [value]
                else:
                    metadata[key] = value
    return metadata

def basic(full_path):
    base_path, name = os.path.split(full_path)
    title, ext = os.path.splitext(name)
    mtime = os.stat(full_path).st_mtime
    if (mtime < 0):
        mtime = 0
    originalAirDate = datetime.fromtimestamp(mtime)

    metadata = {'title': title,
                'originalAirDate': originalAirDate.isoformat()}
    if ext.lower() in ['.mp4', '.m4v', '.mov']:
        metadata.update(from_moov(full_path))
    metadata.update(from_text(full_path))

    return metadata

def from_container(xmldoc):
    metadata = {}

    keys = {'title': 'Title', 'episodeTitle': 'EpisodeTitle',
            'description': 'Description', 'seriesId': 'SeriesId',
            'episodeNumber': 'EpisodeNumber', 'tvRating': 'TvRating',
            'displayMajorNumber': 'SourceChannel', 'callsign': 'SourceStation'}

    details = xmldoc.getElementsByTagName('Details')[0]

    for key in keys:
        data = tag_data(details, keys[key])
        if data:
            if key == 'description':
                data = data.replace(TRIBUNE_CR, '')
            elif key == 'tvRating':
                data = 'x' + data
            elif key == 'displayMajorNumber':
                if '-' in data:
                    data, metadata['displayMinorNumber'] = data.split('-')
            metadata[key] = data

    return metadata

def from_details(xmldoc):
    metadata = {}

    showing = xmldoc.getElementsByTagName('showing')[0]
    program = showing.getElementsByTagName('program')[0]

    items = {'description': 'program/description',
             'title': 'program/title',
             'episodeTitle': 'program/episodeTitle',
             'episodeNumber': 'program/episodeNumber',
             'seriesId': 'program/series/uniqueId',
             'seriesTitle': 'program/series/seriesTitle',
             'originalAirDate': 'program/originalAirDate',
             'isEpisode': 'program/isEpisode',
             'movieYear': 'program/movieYear',
             'partCount': 'partCount',
             'partIndex': 'partIndex'}

    for item in items:
        data = tag_data(showing, items[item])
        if data:
            if item == 'description':
                data = data.replace(TRIBUNE_CR, '')
            metadata[item] = data

    vItems = ['vActor', 'vChoreographer', 'vDirector',
              'vExecProducer', 'vProgramGenre', 'vGuestStar',
              'vHost', 'vProducer', 'vWriter']

    for item in vItems:
        data = _vtag_data(program, item)
        if data:
            metadata[item] = data

    sb = showing.getElementsByTagName('showingBits')
    if sb:
        metadata['showingBits'] = sb[0].attributes['value'].value

    for tag in ['starRating', 'mpaaRating', 'colorCode']:
        value = _tag_value(program, tag)
        if value:
            metadata[tag] = value

    rating = _tag_value(showing, 'tvRating')
    if rating:
        metadata['tvRating'] = 'x' + rating[1]

    return metadata

def from_tivo(full_path):
    if full_path in tivo_cache:
        return tivo_cache[full_path]

    tdcat_path = config.get_bin('tdcat')
    tivo_mak = config.get_server('tivo_mak')
    if tdcat_path and tivo_mak:
        tcmd = [tdcat_path, '-m', tivo_mak, '-2', full_path]
        tdcat = subprocess.Popen(tcmd, stdout=subprocess.PIPE)
        xmldoc = minidom.parse(tdcat.stdout)
        metadata = from_details(xmldoc)
        tivo_cache[full_path] = metadata
    else:
        metadata = {}

    return metadata

if __name__ == '__main__':        
    import sys
    if len(sys.argv) > 1:
        metadata = {}
        ext = os.path.splitext(sys.argv[1])[1].lower()
        if ext == '.tivo':
            config.init([])
            metadata.update(from_tivo(sys.argv[1]))
        elif ext in ['.mp4', '.m4v', '.mov']:
            metadata.update(from_moov(sys.argv[1]))
        for key in metadata:
            value = metadata[key]
            if type(value) == list:
                for item in value:
                    print '%s: %s' % (key, item.encode('utf8'))
            else:
                print '%s: %s' % (key, value.encode('utf8'))
