import ConfigParser
import logging
import logging.config
import os
import re
import random
import string
import sys
from ConfigParser import NoOptionError

guid = ''.join([random.choice(string.letters) for i in range(10)])

config = ConfigParser.ConfigParser()

p = os.path.dirname(__file__)
config_files = ['/etc/pyTivo.conf', os.path.join(p, 'pyTivo.conf')]

configs_found = config.read(config_files)
if not configs_found:
    print ('ERROR: pyTivo.conf does not exist.\n' +
           'You must create this file before running pyTivo.')
    sys.exit(1)

def reset():
    global config
    newconfig = ConfigParser.ConfigParser()
    newconfig.read(config_files)
    config = newconfig

def write():
    f = open(configs_found[-1], 'w')
    config.write(f)
    f.close()

def getGUID():
    if config.has_option('Server', 'GUID'):
        return config.get('Server', 'GUID')
    else:
        return guid

def getTivoUsername():
    return config.get('Server', 'tivo_username')

def getTivoPassword():
    return config.get('Server', 'tivo_password')

def getBeaconAddresses():
    if config.has_option('Server', 'beacon'):
        beacon_ips = config.get('Server', 'beacon')
    else:
        beacon_ips = '255.255.255.255'
    return beacon_ips

def getPort():
    return config.get('Server', 'Port')

def get169Blacklist(tsn):  # tivo does not pad 16:9 video
    return tsn and not isHDtivo(tsn) and not get169Letterbox(tsn)
    # verified Blacklist Tivo's are ('130', '240', '540')
    # It is assumed all remaining non-HD and non-Letterbox tivos are Blacklist

def get169Letterbox(tsn):  # tivo pads 16:9 video for 4:3 display
    return tsn and tsn[:3] in ['649']

def get169Setting(tsn):
    if not tsn:
        return True

    tsnsect = '_tivo_' + tsn
    if config.has_section(tsnsect):
        if config.has_option(tsnsect, 'aspect169'):
            try:
                return config.getboolean(tsnsect, 'aspect169')
            except ValueError:
                pass

    if get169Blacklist(tsn) or get169Letterbox(tsn):
        return False

    return True

def getShares(tsn=''):
    shares = [(section, dict(config.items(section)))
              for section in config.sections()
              if not (section.startswith('_tivo_')
                      or section.startswith('logger_')
                      or section.startswith('handler_')
                      or section.startswith('formatter_')
                      or section in ('Server', 'loggers', 'handlers',
                                     'formatters')
              )
    ]

    tsnsect = '_tivo_' + tsn
    if config.has_section(tsnsect) and config.has_option(tsnsect, 'shares'):
        # clean up leading and trailing spaces & make sure ref is valid
        tsnshares = []
        for x in config.get(tsnsect, 'shares').split(','):
            y = x.strip()
            if config.has_section(y):
                tsnshares.append((y, dict(config.items(y))))
        if tsnshares:
            shares = tsnshares

    return shares

def getDebug():
    try:
        return config.getboolean('Server', 'debug')
    except NoOptionError, ValueError:
        return False

def getOptres(tsn=None):
    if tsn and config.has_section('_tivo_' + tsn):
        try:
            return config.getboolean('_tivo_' + tsn, 'optres')
        except NoOptionError, ValueError:
            pass
    section_name = get_section(tsn)
    if config.has_section(section_name):
        try:
            return config.getboolean(section_name, 'optres')
        except NoOptionError, ValueError:
            pass
    try:
        return config.getboolean('Server', 'optres')
    except NoOptionError, ValueError:
        return False

def getPixelAR(ref):
    if config.has_option('Server', 'par'):
        try:
            return (True, config.getfloat('Server', 'par'))[ref]
        except NoOptionError, ValueError:
            pass
    return (False, 1.0)[ref]

def get(section, key):
    return config.get(section, key)

def getFFmpegWait():
    if config.has_option('Server', 'ffmpeg_wait'):
        return max(int(float(config.get('Server', 'ffmpeg_wait'))), 1)
    else:
        return 10

def getFFmpegTemplate(tsn):
    tmpl = get_tsn('ffmpeg_tmpl', tsn, True)
    if tmpl:
        return tmpl
    return '%(video_codec)s %(video_fps)s %(video_br)s %(max_video_br)s \
            %(buff_size)s %(aspect_ratio)s %(audio_br)s \
            %(audio_fr)s %(audio_ch)s %(audio_codec)s %(audio_lang)s \
            %(ffmpeg_pram)s %(format)s'

def getFFmpegPrams(tsn):
    return get_tsn('ffmpeg_pram', tsn, True)

def isHDtivo(tsn):  # tsn's of High Definition Tivo's
    return bool(tsn and tsn[:3] in ['648', '652', '658', '663'])

def getValidWidths():
    return [1920, 1440, 1280, 720, 704, 544, 480, 352]

def getValidHeights():
    return [1080, 720, 480] # Technically 240 is also supported

# Return the number in list that is nearest to x
# if two values are equidistant, return the larger
def nearest(x, list):
    return reduce(lambda a, b: closest(x, a, b), list)

def closest(x, a, b):
    da = abs(x - a)
    db = abs(x - b)
    if da < db or (da == db and a > b):
        return a
    else:
        return b

def nearestTivoHeight(height):
    return nearest(height, getValidHeights())

def nearestTivoWidth(width):
    return nearest(width, getValidWidths())

def getTivoHeight(tsn):
    height = get_tsn('height', tsn)
    if height:
        return nearestTivoHeight(int(height))
    return [480, 720][isHDtivo(tsn)]

def getTivoWidth(tsn):
    width = get_tsn('width', tsn)
    if width:
        return nearestTivoWidth(int(width))
    return [544, 1280][isHDtivo(tsn)]

def _trunc64(i):
    return max(int(strtod(i)) / 64000, 1) * 64

def getAudioBR(tsn=None):
    rate = get_tsn('audio_br', tsn)
    if not rate:
        rate = '448k'
    # convert to non-zero multiple of 64 to ensure ffmpeg compatibility
    # compare audio_br to max_audio_br and return lowest
    return str(min(_trunc64(rate), getMaxAudioBR(tsn))) + 'k'

def _k(i):
    return str(int(strtod(i)) / 1000) + 'k'

def getVideoBR(tsn=None):
    rate = get_tsn('video_br', tsn)
    if rate:
        return _k(rate)
    return ['4096K', '16384K'][isHDtivo(tsn)]

def getMaxVideoBR(tsn=None):
    rate = get_tsn('max_video_br', tsn)
    if rate:
        return _k(rate)
    return '30000k'

def getVideoPCT(tsn=None):
    pct = get_tsn('video_pct', tsn)
    if pct:
        return float(pct)
    return 85

def getBuffSize(tsn=None):
    size = get_tsn('bufsize', tsn)
    if size:
        return _k(size)
    return ['1024k', '4096k'][isHDtivo(tsn)]

def getMaxAudioBR(tsn=None):
    rate = get_tsn('max_audio_br', tsn)
    # convert to non-zero multiple of 64 for ffmpeg compatibility
    if rate:
        return _trunc64(rate)
    return 448

def get_section(tsn):
    return ['_tivo_SD', '_tivo_HD'][isHDtivo(tsn)]

def get_tsn(name, tsn=None, raw=False):
    if tsn and config.has_section('_tivo_' + tsn):
        try:
            return config.get('_tivo_' + tsn, name, raw)
        except NoOptionError:
            pass
    section_name = get_section(tsn)
    if config.has_section(section_name):
        try:
            return config.get(section_name, name, raw)
        except NoOptionError:
            pass
    try:
        return config.get('Server', name, raw)
    except NoOptionError:
        pass
    return None

def getAudioCodec(tsn=None):
    return get_tsn('audio_codec', tsn)

def getAudioCH(tsn=None):
    return get_tsn('audio_ch', tsn)

def getAudioFR(tsn=None):
    return get_tsn('audio_fr', tsn)

def getAudioLang(tsn=None):
    return get_tsn('audio_lang', tsn)

def getCopyTS(tsn=None):
    return get_tsn('copy_ts', tsn)

def getVideoFPS(tsn=None):
    return get_tsn('video_fps', tsn)

def getFormat(tsn=None):
    return get_tsn('format', tsn)

# Parse a bitrate using the SI/IEEE suffix values as if by ffmpeg
# For example, 2K==2000, 2Ki==2048, 2MB==16000000, 2MiB==16777216
# Algorithm: http://svn.mplayerhq.hu/ffmpeg/trunk/libavcodec/eval.c
def strtod(value):
    prefixes = {'y': -24, 'z': -21, 'a': -18, 'f': -15, 'p': -12,
                'n': -9,  'u': -6,  'm': -3,  'c': -2,  'd': -1,
                'h': 2,   'k': 3,   'K': 3,   'M': 6,   'G': 9,
                'T': 12,  'P': 15,  'E': 18,  'Z': 21,  'Y': 24}
    p = re.compile(r'^(\d+)(?:([yzafpnumcdhkKMGTPEZY])(i)?)?([Bb])?$')
    m = p.match(value)
    if not m:
        raise SyntaxError('Invalid bit value syntax')
    (coef, prefix, power, byte) = m.groups()
    if prefix is None:
        value = float(coef)
    else:
        exponent = float(prefixes[prefix])
        if power == 'i':
            # Use powers of 2
            value = float(coef) * pow(2.0, exponent / 0.3)
        else:
            # Use powers of 10
            value = float(coef) * pow(10.0, exponent)
    if byte == 'B': # B == Byte, b == bit
        value *= 8;
    return value

def init_logging():
    if (config.has_section('loggers') and
        config.has_section('handlers') and
        config.has_section('formatters')):

        logging.config.fileConfig(config_files)

    elif getDebug():
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
