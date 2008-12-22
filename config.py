import ConfigParser, os, sys
import re
import random
import string
from ConfigParser import NoOptionError

guid = ''.join([random.choice(string.letters) for i in range(10)])

config = ConfigParser.ConfigParser()
p = os.path.dirname(__file__)

config_files = [
    '/etc/pyTivo.conf',
    os.path.join(p, 'pyTivo.conf'),
]
config_exists = False
for config_file in config_files:
    if os.path.exists(config_file):
        config_exists = True
if not config_exists:
    print 'ERROR:  pyTivo.conf does not exist.\n' + \
          'You must create this file before running pyTivo.'
    sys.exit(1)
config.read(config_files)

def reset():
    global config
    del config
    config = ConfigParser.ConfigParser()
    config.read(config_files)

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

def get169Letterbox(tsn):  # tivo pads 16:9 video for 4:3 display
    return tsn and tsn[:3] in ('649')

def get169Setting(tsn):
    if not tsn:
        return True

    if config.has_section('_tivo_' + tsn):
        if config.has_option('_tivo_' + tsn, 'aspect169'):
            try:
                return config.getboolean('_tivo_' + tsn, 'aspect169')
            except ValueError:
                pass

    if get169Blacklist(tsn) or get169Letterbox(tsn):
        return False

    return True

def getShares(tsn=''):
    shares = [(section, dict(config.items(section)))
              for section in config.sections()
              if not (section.startswith(('_tivo_', 'logger_', 'handler_',
                                          'formatter_'))
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

def getOptres(tsn = None):
    if tsn and config.has_section('_tivo_' + tsn):
        try:
            return config.getboolean('_tivo_' + tsn, 'optres')
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

def getFFmpegTemplate(tsn):
    if tsn and config.has_section('_tivo_' + tsn):
        try:
            return config.get('_tivo_' + tsn, 'ffmpeg_tmpl', raw=True)
        except NoOptionError:
            pass
    try:
        return config.get('Server', 'ffmpeg_tmpl', raw=True)
    except NoOptionError: #default
        return '%(video_codec)s %(video_fps)s %(video_br)s %(max_video_br)s \
                %(buff_size)s %(aspect_ratio)s -comment pyTivo.py %(audio_br)s \
                %(audio_fr)s %(audio_ch)s %(audio_codec)s %(audio_lang)s \
                %(ffmpeg_pram)s %(format)s'

def getFFmpegPrams(tsn):
    if tsn and config.has_section('_tivo_' + tsn):
        try:
            return config.get('_tivo_' + tsn, 'ffmpeg_pram', raw=True)
        except NoOptionError:
            pass
    try:
        return config.get('Server', 'ffmpeg_pram', raw=True)
    except NoOptionError:
        return None

def isHDtivo(tsn):  # tsn's of High Definition Tivo's
    return tsn and tsn[:3] in ['648', '652', '658']

def getValidWidths():
    return [1920, 1440, 1280, 720, 704, 544, 480, 352]

def getValidHeights():
    return [1080, 720, 480] # Technically 240 is also supported

# Return the number in list that is nearest to x
# if two values are equidistant, return the larger
def nearest(x, list):
    return reduce(lambda a, b: closest(x, a, b), list)

def closest(x, a, b):
    if abs(x - a) < abs(x - b) or (abs(x - a) == abs(x - b) and a > b):
        return a
    else:
        return b

def nearestTivoHeight(height):
    return nearest(height, getValidHeights())

def nearestTivoWidth(width):
    return nearest(width, getValidWidths())

def getTivoHeight(tsn):
    if tsn and config.has_section('_tivo_' + tsn):
        try:
            height = config.getint('_tivo_' + tsn, 'height')
            return nearestTivoHeight(height)
        except NoOptionError:
            pass
    try:
        height = config.getint('Server', 'height')
        return nearestTivoHeight(height)
    except NoOptionError: #defaults for S3/S2 TiVo
        if isHDtivo(tsn):
            return 720
        else:
            return 480

def getTivoWidth(tsn):
    if tsn and config.has_section('_tivo_' + tsn):
        try:
            width = config.getint('_tivo_' + tsn, 'width')
            return nearestTivoWidth(width)
        except NoOptionError:
            pass
    try:
        width = config.getint('Server', 'width')
        return nearestTivoWidth(width)
    except NoOptionError: #defaults for S3/S2 TiVo
        if isHDtivo(tsn):
            return 1280
        else:
            return 544

def _trunc64(i):
    return max(int(strtod(i)) / 64000, 1) * 64

def getAudioBR(tsn = None):
    #convert to non-zero multiple of 64 to ensure ffmpeg compatibility
    #compare audio_br to max_audio_br and return lowest
    if tsn and config.has_section('_tivo_' + tsn):
        try:
            audiobr = _trunc64(config.get('_tivo_' + tsn, 'audio_br'))
            return str(min(audiobr, getMaxAudioBR(tsn))) + 'k'
        except NoOptionError:
            pass
    try:
        audiobr = _trunc64(config.get('Server', 'audio_br'))
        return str(min(audiobr, getMaxAudioBR(tsn))) + 'k'
    except NoOptionError:
        return str(min(384, getMaxAudioBR(tsn))) + 'k'

def _k(i):
    return str(int(strtod(i)) / 1000) + 'k'

def getVideoBR(tsn = None):
    if tsn and config.has_section('_tivo_' + tsn):
        try:
            return _k(config.get('_tivo_' + tsn, 'video_br'))
        except NoOptionError:
            pass
    try:
        return _k(config.get('Server', 'video_br'))
    except NoOptionError: #defaults for S3/S2 TiVo
        if isHDtivo(tsn):
            return '8192k'
        else:
            return '4096K'

def getMaxVideoBR():
    try:
        return _k(config.get('Server', 'max_video_br'))
    except NoOptionError: #default to 30000k
        return '30000k'

def getVideoPCT():
    try:
        return config.getfloat('Server', 'video_pct')
    except NoOptionError:
        return 70

def getBuffSize(tsn = None):
    if tsn and config.has_section('_tivo_' + tsn):
        if config.has_option('_tivo_' + tsn, 'bufsize'):
            try:
                return _k(config.get('_tivo_' + tsn, 'bufsize'))
            except NoOptionError:
                pass
    if config.has_option('Server', 'bufsize'):
        try:
            return _k(config.get('Server', 'bufsize'))
        except NoOptionError:
            pass
    if isHDtivo(tsn):
        return '4096k'
    else:
        return '1024k'

def getMaxAudioBR(tsn = None):
    #convert to non-zero multiple of 64 for ffmpeg compatibility
    if tsn and config.has_section('_tivo_' + tsn):
        try:
            return _trunc64(config.get('_tivo_' + tsn, 'max_audio_br'))
        except NoOptionError:
            pass
    try:
        return _trunc64(config.get('Server', 'max_audio_br'))
    except NoOptionError:
        return int(448) #default to 448

def get_tsn(name, tsn=None):
    if tsn and config.has_section('_tivo_' + tsn):
        try:
            return config.get('_tivo_' + tsn, name)
        except NoOptionError:
            pass
    try:
        return config.get('Server', name)
    except NoOptionError:
        return None

def getAudioCodec(tsn=None):
    return get_tsn('audio_codec', tsn)

def getAudioCH(tsn=None):
    return get_tsn('audio_ch', tsn)

def getAudioFR(tsn=None):
    return get_tsn('audio_fr', tsn)

def getAudioLang(tsn=None):
    return get_tsn('audio_lang', tsn)

def getCopyTS(tsn = None):
    if tsn and config.has_section('_tivo_' + tsn):
        if config.has_option('_tivo_' + tsn, 'copy_ts'):
            try:
                return config.get('_tivo_' + tsn, 'copy_ts')
            except NoOptionError, ValueError:
                pass
    if config.has_option('Server', 'copy_ts'):
        try:
            return config.get('Server', 'copy_ts')
        except NoOptionError, ValueError:
            pass
    return 'none'

def getVideoFPS(tsn=None):
    return get_tsn('video_fps', tsn)

def getVideoCodec(tsn=None):
    return get_tsn('video_codec', tsn)

def getFormat(tsn = None):
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
    if m is None:
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
