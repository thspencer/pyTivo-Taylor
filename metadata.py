#!/usr/bin/env python

import os
import subprocess
from datetime import datetime
from xml.dom import minidom

from lrucache import LRUCache

import config

# Something to strip
TRIBUNE_CR = ' Copyright Tribune Media Services, Inc.'

tivo_cache = LRUCache(50)

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

def from_text(full_path):
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

def basic(full_path):
    base_path, title = os.path.split(full_path)
    mtime = os.stat(full_path).st_mtime
    if (mtime < 0):
        mtime = 0
    originalAirDate = datetime.fromtimestamp(mtime)

    metadata = {'title': '.'.join(title.split('.')[:-1]),
                'originalAirDate': originalAirDate.isoformat()}

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
        config.init([])
        metadata = from_tivo(sys.argv[1])
        for key in metadata:
            value = metadata[key]
            if type(value) == list:
                for item in value:
                    print '%s: %s' % (key, item.encode('utf8'))
            else:
                print '%s: %s' % (key, value.encode('utf8'))
