import logging
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import lrucache

import config
import metadata

logger = logging.getLogger('pyTivo.video.transcode')

info_cache = lrucache.LRUCache(1000)
ffmpeg_procs = {}
reapers = {}

GOOD_MPEG_FPS = ['23.98', '24.00', '25.00', '29.97',
                 '30.00', '50.00', '59.94', '60.00']

BLOCKSIZE = 512 * 1024
MAXBLOCKS = 2
TIMEOUT = 600

UNSET = 0
OLD_PAD = 1
NEW_PAD = 2

pad_style = UNSET

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

def debug(msg):
    if type(msg) == str:
        try:
            msg = msg.decode('utf8')
        except:
            if sys.platform == 'darwin':
                msg = msg.decode('macroman')
            else:
                msg = msg.decode('iso8859-1')
    logger.debug(msg)

def transcode(isQuery, inFile, outFile, tsn='', mime='', thead=''):
    settings = {'video_codec': select_videocodec(inFile, tsn),
                'video_br': select_videobr(inFile, tsn),
                'video_fps': select_videofps(inFile, tsn),
                'max_video_br': select_maxvideobr(tsn),
                'buff_size': select_buffsize(tsn),
                'aspect_ratio': ' '.join(select_aspect(inFile, tsn)),
                'audio_br': select_audiobr(tsn),
                'audio_fr': select_audiofr(inFile, tsn),
                'audio_ch': select_audioch(tsn),
                'audio_codec': select_audiocodec(isQuery, inFile, tsn),
                'audio_lang': select_audiolang(inFile, tsn),
                'ffmpeg_pram': select_ffmpegprams(tsn),
                'format': select_format(tsn, mime)}

    if isQuery:
        return settings

    ffmpeg_path = config.get_bin('ffmpeg')
    cmd_string = config.getFFmpegTemplate(tsn) % settings
    fname = unicode(inFile, 'utf-8')
    if mswindows:
        fname = fname.encode('iso8859-1')

    if inFile[-5:].lower() == '.tivo':
        tivodecode_path = config.get_bin('tivodecode')
        tivo_mak = config.get_server('tivo_mak')
        tcmd = [tivodecode_path, '-m', tivo_mak, fname]
        tivodecode = subprocess.Popen(tcmd, stdout=subprocess.PIPE,
                                      bufsize=(512 * 1024))
        if tivo_compatible(inFile, tsn)[0]:
            cmd = ''
            ffmpeg = tivodecode
        else:
            cmd = [ffmpeg_path, '-i', '-'] + cmd_string.split()
            ffmpeg = subprocess.Popen(cmd, stdin=tivodecode.stdout,
                                      stdout=subprocess.PIPE,
                                      bufsize=(512 * 1024))
    else:
        cmd = [ffmpeg_path, '-i', fname] + cmd_string.split()
        ffmpeg = subprocess.Popen(cmd, bufsize=(512 * 1024),
                                  stdout=subprocess.PIPE)

    if cmd:
        debug('transcoding to tivo model ' + tsn[:3] + ' using ffmpeg command:')
        debug(' '.join(cmd))

    ffmpeg_procs[inFile] = {'process': ffmpeg, 'start': 0, 'end': 0, 
                            'last_read': time.time(), 'blocks': []}
    if thead:
        ffmpeg_procs[inFile]['blocks'].append(thead)
    reap_process(inFile)
    return resume_transfer(inFile, outFile, 0)

def is_resumable(inFile, offset):
    if inFile in ffmpeg_procs:
        proc = ffmpeg_procs[inFile]
        if proc['start'] <= offset < proc['end']:
            return True
        else:
            cleanup(inFile)
            kill(proc['process'])
    return False

def resume_transfer(inFile, outFile, offset):
    proc = ffmpeg_procs[inFile]
    offset -= proc['start']
    count = 0

    try:
        for block in proc['blocks']:
            length = len(block)
            if offset < length:
                if offset > 0:
                    block = block[offset:]
                outFile.write('%x\r\n' % len(block))
                outFile.write(block)
                outFile.write('\r\n')
                count += len(block)
            offset -= length
        outFile.flush()
    except Exception, msg:
        logger.info(msg)
        return count

    proc['start'] = proc['end']
    proc['blocks'] = []

    return count + transfer_blocks(inFile, outFile)

def transfer_blocks(inFile, outFile):
    proc = ffmpeg_procs[inFile]
    blocks = proc['blocks']
    count = 0

    while True:
        try:
            block = proc['process'].stdout.read(BLOCKSIZE)
            proc['last_read'] = time.time()
        except Exception, msg:
            logger.info(msg)
            cleanup(inFile)
            kill(proc['process'])
            break

        if not block:
            try:
                outFile.flush()
            except Exception, msg:
                logger.info(msg)
            else:
                cleanup(inFile)
            break

        blocks.append(block)
        proc['end'] += len(block)
        if len(blocks) > MAXBLOCKS:
            proc['start'] += len(blocks[0])
            blocks.pop(0)

        try:
            outFile.write('%x\r\n' % len(block))
            outFile.write(block)
            outFile.write('\r\n')
            count += len(block)
        except Exception, msg:
            logger.info(msg)
            break

    return count

def reap_process(inFile):
    if ffmpeg_procs and inFile in ffmpeg_procs:
        proc = ffmpeg_procs[inFile]
        if proc['last_read'] + TIMEOUT < time.time():
            del ffmpeg_procs[inFile]
            del reapers[inFile]
            kill(proc['process'])
        else:
            reaper = threading.Timer(TIMEOUT, reap_process, (inFile,))
            reapers[inFile] = reaper
            reaper.start()

def cleanup(inFile):
    del ffmpeg_procs[inFile]
    reapers[inFile].cancel()
    del reapers[inFile]

def select_audiocodec(isQuery, inFile, tsn=''):
    if inFile[-5:].lower() == '.tivo':
        return '-acodec copy'
    vInfo = video_info(inFile)
    codectype = vInfo['vCodec']
    codec = config.get_tsn('audio_codec', tsn)
    if not codec:
        # Default, compatible with all TiVo's
        codec = 'ac3'
        if vInfo['aCodec'] in ('ac3', 'liba52', 'mp2'):
            aKbps = vInfo['aKbps']
            if aKbps == None:
                if not isQuery:
                    aKbps = audio_check(inFile, tsn)
                else:
                    codec = 'TBD'
            if aKbps != None and int(aKbps) <= config.getMaxAudioBR(tsn):
                # compatible codec and bitrate, do not reencode audio
                codec = 'copy'
    copy_flag = config.get_tsn('copy_ts', tsn)
    copyts = ' -copyts'
    if ((codec == 'copy' and codectype == 'mpeg2video' and not copy_flag) or
        (copy_flag and copy_flag.lower() == 'false')):
        copyts = ''
    return '-acodec ' + codec + copyts

def select_audiofr(inFile, tsn):
    freq = '48000'  #default
    vInfo = video_info(inFile)
    if not vInfo['aFreq'] == None and vInfo['aFreq'] in ('44100', '48000'):
        # compatible frequency
        freq = vInfo['aFreq']
    audio_fr = config.get_tsn('audio_fr', tsn)
    if audio_fr != None:
        freq = audio_fr
    return '-ar ' + freq

def select_audioch(tsn):
    ch = config.get_tsn('audio_ch', tsn)
    if ch:
        return '-ac ' + ch
    return ''

def select_audiolang(inFile, tsn):
    vInfo = video_info(inFile)
    audio_lang = config.get_tsn('audio_lang', tsn)
    if audio_lang != None and vInfo['mapVideo'] != None:
        stream = vInfo['mapAudio'][0][0]
        langmatch = []
        for lang in audio_lang.replace(' ','').lower().split(','):
            for s, l in vInfo['mapAudio']:
                if lang in s + l.replace(' ','').lower():
                    langmatch.append(s)
                    stream = s
                    break
            if langmatch: break
        if stream is not '':
            return '-map ' + vInfo['mapVideo'] + ' -map ' + stream
    return ''

def select_videofps(inFile, tsn):
    vInfo = video_info(inFile)
    fps = '-r 29.97'  # default
    if config.isHDtivo(tsn) and vInfo['vFps'] in GOOD_MPEG_FPS:
        fps = ' '
    video_fps = config.get_tsn('video_fps', tsn)
    if video_fps != None:
        fps = '-r ' + video_fps
    return fps

def select_videocodec(inFile, tsn):
    vInfo = video_info(inFile)
    if tivo_compatible_video(vInfo, tsn)[0]:
        codec = 'copy'
    else:
        codec = 'mpeg2video'  # default
    return '-vcodec ' + codec

def select_videobr(inFile, tsn):
    return '-b ' + str(select_videostr(inFile, tsn) / 1000) + 'k'

def select_videostr(inFile, tsn):
    vInfo = video_info(inFile)
    if tivo_compatible_video(vInfo, tsn)[0]:
        video_str = int(vInfo['kbps'])
        if vInfo['aKbps']:
            video_str -= int(vInfo['aKbps'])
        video_str *= 1000
    else:
        video_str = config.strtod(config.getVideoBR(tsn))
        if config.isHDtivo(tsn):
            if vInfo['kbps'] != None and config.getVideoPCT(tsn) > 0:
                video_percent = (int(vInfo['kbps']) * 10 *
                                 config.getVideoPCT(tsn))
                video_str = max(video_str, video_percent)
        video_str = int(min(config.strtod(config.getMaxVideoBR(tsn)) * 0.95,
                            video_str))
    return video_str

def select_audiobr(tsn):
    return '-ab ' + config.getAudioBR(tsn)

def select_maxvideobr(tsn):
    return '-maxrate ' + config.getMaxVideoBR(tsn)

def select_buffsize(tsn):
    return '-bufsize ' + config.getBuffSize(tsn)

def select_ffmpegprams(tsn):
    params = config.getFFmpegPrams(tsn)
    if not params:
        params = ''
    return params

def select_format(tsn, mime):
    if mime == 'video/x-tivo-mpeg-ts':
        fmt = 'mpegts'
    else:
        fmt = 'vob'
    return '-f %s -' % fmt

def pad_check():
    global pad_style
    if pad_style == UNSET:
        pad_style = OLD_PAD
        filters = tempfile.TemporaryFile()
        cmd = [config.get_bin('ffmpeg'), '-filters']
        ffmpeg = subprocess.Popen(cmd, stdout=filters, stderr=subprocess.PIPE)
        ffmpeg.wait()
        filters.seek(0)
        for line in filters:
            if line.startswith('pad'):
                pad_style = NEW_PAD
                break
        filters.close()
    return pad_style == NEW_PAD

def pad_TB(TIVO_WIDTH, TIVO_HEIGHT, multiplier, vInfo):
    endHeight = int(((TIVO_WIDTH * vInfo['vHeight']) /
                      vInfo['vWidth']) * multiplier)
    if endHeight % 2:
        endHeight -= 1
    if endHeight < TIVO_HEIGHT * 0.99:
        topPadding = (TIVO_HEIGHT - endHeight) / 2
        if topPadding % 2:
            topPadding -= 1
        newpad = pad_check()
        if newpad:
            return ['-s', '%sx%s' % (TIVO_WIDTH, endHeight), '-vf',
                    'pad=%d:%d:0:%d' % (TIVO_WIDTH, TIVO_HEIGHT, topPadding)]
        else:
            bottomPadding = (TIVO_HEIGHT - endHeight) - topPadding
            return ['-s', '%sx%s' % (TIVO_WIDTH, endHeight),
                    '-padtop', str(topPadding),
                    '-padbottom', str(bottomPadding)]
    else: # if only very small amount of padding needed, then
          # just stretch it
        return ['-s', '%sx%s' % (TIVO_WIDTH, TIVO_HEIGHT)]

def pad_LR(TIVO_WIDTH, TIVO_HEIGHT, multiplier, vInfo):
    endWidth = int((TIVO_HEIGHT * vInfo['vWidth']) / 
                   (vInfo['vHeight'] * multiplier))
    if endWidth % 2:
        endWidth -= 1
    if endWidth < TIVO_WIDTH * 0.99:
        leftPadding = (TIVO_WIDTH - endWidth) / 2
        if leftPadding % 2:
            leftPadding -= 1
        newpad = pad_check()
        if newpad:
            return ['-s', '%sx%s' % (endWidth, TIVO_HEIGHT), '-vf',
                    'pad=%d:%d:%d:0' % (TIVO_WIDTH, TIVO_HEIGHT, leftPadding)]
        else:
            rightPadding = (TIVO_WIDTH - endWidth) - leftPadding
            return ['-s', '%sx%s' % (endWidth, TIVO_HEIGHT),
                    '-padleft', str(leftPadding),
                    '-padright', str(rightPadding)]
    else: # if only very small amount of padding needed, then 
          # just stretch it
        return ['-s', '%sx%s' % (TIVO_WIDTH, TIVO_HEIGHT)]

def select_aspect(inFile, tsn = ''):
    TIVO_WIDTH = config.getTivoWidth(tsn)
    TIVO_HEIGHT = config.getTivoHeight(tsn)

    vInfo = video_info(inFile)

    debug('tsn: %s' % tsn)

    aspect169 = config.get169Setting(tsn)

    debug('aspect169: %s' % aspect169)

    optres = config.getOptres(tsn)

    debug('optres: %s' % optres)

    if optres:
        optHeight = config.nearestTivoHeight(vInfo['vHeight'])
        optWidth = config.nearestTivoWidth(vInfo['vWidth'])
        if optHeight < TIVO_HEIGHT:
            TIVO_HEIGHT = optHeight
        if optWidth < TIVO_WIDTH:
            TIVO_WIDTH = optWidth

    if vInfo.get('par2'):
        par2 = vInfo['par2']
    elif vInfo.get('par'):
        par2 = float(vInfo['par'])
    else:
        # Assume PAR = 1.0
        par2 = 1.0

    debug(('File=%s vCodec=%s vWidth=%s vHeight=%s vFps=%s millisecs=%s ' +
           'TIVO_HEIGHT=%s TIVO_WIDTH=%s') % (inFile, vInfo['vCodec'],
          vInfo['vWidth'], vInfo['vHeight'], vInfo['vFps'],
          vInfo['millisecs'], TIVO_HEIGHT, TIVO_WIDTH))

    if config.isHDtivo(tsn) and not optres:
        if config.getPixelAR(0) or vInfo['par']:
            if vInfo['par2'] == None:
                if vInfo['par']:
                    npar = par2
                else:
                    npar = config.getPixelAR(1)
            else:
                npar = par2

            # adjust for pixel aspect ratio, if set

            if npar < 1.0:
                return ['-s', '%dx%d' % (vInfo['vWidth'],
                                         math.ceil(vInfo['vHeight'] / npar))]
            elif npar > 1.0:
                # FFMPEG expects width to be a multiple of two
                return ['-s', '%dx%d' % (math.ceil(vInfo['vWidth']*npar/2.0)*2,
                                         vInfo['vHeight'])]

        if vInfo['vHeight'] <= TIVO_HEIGHT:
            # pass all resolutions to S3, except heights greater than 
            # conf height
            return []
        # else, resize video.

    d = gcd(vInfo['vHeight'], vInfo['vWidth'])
    rheight, rwidth = vInfo['vHeight'] / d, vInfo['vWidth'] / d
    debug('rheight=%s rwidth=%s' % (rheight, rwidth))

    if (rwidth, rheight) in [(1, 1)] and vInfo['par1'] == '8:9':
        debug('File + PAR is within 4:3.')
        return ['-aspect', '4:3', '-s', '%sx%s' % (TIVO_WIDTH, TIVO_HEIGHT)]

    elif ((rwidth, rheight) in [(4, 3), (10, 11), (15, 11), (59, 54), 
                                (59, 72), (59, 36), (59, 54)] or
          vInfo['dar1'] == '4:3'):
        debug('File is within 4:3 list.')
        return ['-aspect', '4:3', '-s', '%sx%s' % (TIVO_WIDTH, TIVO_HEIGHT)]

    elif (((rwidth, rheight) in [(16, 9), (20, 11), (40, 33), (118, 81), 
                                (59, 27)] or vInfo['dar1'] == '16:9')
          and (aspect169 or config.get169Letterbox(tsn))):
        debug('File is within 16:9 list and 16:9 allowed.')

        if config.get169Blacklist(tsn) or (aspect169 and 
                                           config.get169Letterbox(tsn)):
            aspect = '4:3'
        else:
            aspect = '16:9'
        return ['-aspect', aspect, '-s', '%sx%s' % (TIVO_WIDTH, TIVO_HEIGHT)]

    else:
        settings = ['-aspect']

        multiplier16by9 = (16.0 * TIVO_HEIGHT) / (9.0 * TIVO_WIDTH) / par2
        multiplier4by3  =  (4.0 * TIVO_HEIGHT) / (3.0 * TIVO_WIDTH) / par2
        ratio = vInfo['vWidth'] * 100 * par2 / vInfo['vHeight']
        debug('par2=%.3f ratio=%.3f mult4by3=%.3f' % (par2, ratio,
                                                      multiplier4by3))

        # If video is wider than 4:3 add top and bottom padding

        if ratio > 133: # Might be 16:9 file, or just need padding on 
                        # top and bottom

            if aspect169 and ratio > 135: # If file would fall in 4:3 
                                          # assume it is supposed to be 4:3

                if (config.get169Blacklist(tsn) or
                    config.get169Letterbox(tsn)):
                    settings.append('4:3')
                else:
                    settings.append('16:9')

                if ratio > 177: # too short needs padding top and bottom
                    settings += pad_TB(TIVO_WIDTH, TIVO_HEIGHT,
                                       multiplier16by9, vInfo)
                    debug(('16:9 aspect allowed, file is wider ' +
                           'than 16:9 padding top and bottom\n%s') %
                          ' '.join(settings))

                else: # too skinny needs padding on left and right.
                    settings += pad_LR(TIVO_WIDTH, TIVO_HEIGHT,
                                       multiplier16by9, vInfo)
                    debug(('16:9 aspect allowed, file is narrower ' +
                           'than 16:9 padding left and right\n%s') %
                          ' '.join(settings))

            else: # this is a 4:3 file or 16:9 output not allowed
                if ratio > 135 and config.get169Letterbox(tsn):
                    settings.append('16:9')
                    multiplier = multiplier16by9
                else:
                    settings.append('4:3')
                    multiplier = multiplier4by3
                settings += pad_TB(TIVO_WIDTH, TIVO_HEIGHT,
                                   multiplier, vInfo)
                debug(('File is wider than 4:3 padding ' +
                       'top and bottom\n%s') % ' '.join(settings))

        # If video is taller than 4:3 add left and right padding, this 
        # is rare. All of these files will always be sent in an aspect 
        # ratio of 4:3 since they are so narrow.

        else:
            settings.append('4:3')
            settings += pad_LR(TIVO_WIDTH, TIVO_HEIGHT, multiplier4by3, vInfo)
            debug('File is taller than 4:3 padding left and right\n%s'
                  % ' '.join(settings))

        return settings

def tivo_compatible_video(vInfo, tsn, mime=''):
    message = (True, '')
    while True:
        codec = vInfo.get('vCodec', '')
        if mime == 'video/mp4':
            if codec != 'h264':
                message = (False, 'vCodec %s not compatible' % codec)

            break

        if mime == 'video/bif':
            if codec != 'vc1':
                message = (False, 'vCodec %s not compatible' % codec)

            break

        if codec not in ('mpeg2video', 'mpeg1video'):
            message = (False, 'vCodec %s not compatible' % codec)
            break

        if vInfo['kbps'] != None:
            abit = max('0', vInfo['aKbps'])
            if (int(vInfo['kbps']) - int(abit) > 
                config.strtod(config.getMaxVideoBR(tsn)) / 1000):
                message = (False, '%s kbps exceeds max video bitrate' %
                                  vInfo['kbps'])
                break
        else:
            message = (False, '%s kbps not supported' % vInfo['kbps'])
            break

        if config.isHDtivo(tsn):
            if vInfo['par2'] != 1.0:
                if config.getPixelAR(0):
                    if vInfo['par2'] != None or config.getPixelAR(1) != 1.0:
                        message = (False, '%s not correct PAR' % vInfo['par2'])
                        break
            # HD Tivo detected, skipping remaining tests.
            break

        if not vInfo['vFps'] in ['29.97', '59.94']:
            message = (False, '%s vFps, should be 29.97' % vInfo['vFps'])
            break

        if ((config.get169Blacklist(tsn) and not config.get169Setting(tsn))
            or (config.get169Letterbox(tsn) and config.get169Setting(tsn))):
            if vInfo['dar1'] and vInfo['dar1'] not in ('4:3', '8:9', '880:657'):
                message = (False, ('DAR %s not supported ' +
                                   'by BLACKLIST_169 tivos') % vInfo['dar1'])
                break

        mode = (vInfo['vWidth'], vInfo['vHeight'])
        if mode not in [(720, 480), (704, 480), (544, 480),
                        (528, 480), (480, 480), (352, 480), (352, 240)]:
            message = (False, '%s x %s not in supported modes' % mode)
        break

    return message

def tivo_compatible_audio(vInfo, inFile, tsn, mime=''):
    message = (True, '')
    while True:
        codec = vInfo.get('aCodec', '')
        if mime == 'video/mp4':
            if codec not in ('mpeg4aac', 'libfaad', 'mp4a', 'aac', 
                             'ac3', 'liba52'):
                message = (False, 'aCodec %s not compatible' % codec)

            break

        if mime == 'video/bif':
            if codec != 'wmav2':
                message = (False, 'aCodec %s not compatible' % codec)

            break

        if inFile[-5:].lower() == '.tivo':
            break

        if mime == 'video/x-tivo-mpeg-ts' and codec not in ('ac3', 'liba52'):
            message = (False, 'aCodec %s not compatible' % codec)
            break

        if codec not in ('ac3', 'liba52', 'mp2'):
            message = (False, 'aCodec %s not compatible' % codec)
            break

        if (not vInfo['aKbps'] or
            int(vInfo['aKbps']) > config.getMaxAudioBR(tsn)):
            message = (False, '%s kbps exceeds max audio bitrate' %
                              vInfo['aKbps'])
            break

        audio_lang = config.get_tsn('audio_lang', tsn)
        if audio_lang:
            if vInfo['mapAudio'][0][0] != select_audiolang(inFile, tsn)[-3:]:
                message = (False, '%s preferred audio track exists' % 
                                  audio_lang)
        break

    return message

def tivo_compatible_container(vInfo, inFile, mime=''):
    message = (True, '')
    container = vInfo.get('container', '')
    if ((mime == 'video/mp4' and
         (container != 'mov' or inFile.lower().endswith('.mov'))) or
        (mime == 'video/bif' and container != 'asf') or
        (mime == 'video/x-tivo-mpeg-ts' and container != 'mpegts') or
        (mime in ['video/x-tivo-mpeg', 'video/mpeg', ''] and
         (container != 'mpeg' or vInfo['vCodec'] == 'mpeg1video'))):
        message = (False, 'container %s not compatible' % container)

    return message

def mp4_remuxable(inFile, tsn=''):
    vInfo = video_info(inFile)
    return (tivo_compatible_video(vInfo, tsn, 'video/mp4')[0] and
            tivo_compatible_audio(vInfo, inFile, tsn, 'video/mp4')[0])

def mp4_remux(inFile, basename):
    outFile = inFile + '.pyTivo-temp'
    newname = basename + '.pyTivo-temp'
    if os.path.exists(outFile):
        return None  # ugh!

    ffmpeg_path = config.get_bin('ffmpeg')
    fname = unicode(inFile, 'utf-8')
    oname = unicode(outFile, 'utf-8')
    if mswindows:
        fname = fname.encode('iso8859-1')
        oname = oname.encode('iso8859-1')

    cmd = [ffmpeg_path, '-i', fname, '-vcodec', 'copy', '-acodec',
           'copy', '-f', 'mp4', oname]
    ffmpeg = subprocess.Popen(cmd)
    debug('remuxing ' + inFile + ' to ' + outFile)
    if ffmpeg.wait():
        debug('error during remuxing')
        os.remove(outFile)
        return None

    return newname

def tivo_compatible(inFile, tsn='', mime=''):
    vInfo = video_info(inFile)

    message = (True, 'all compatible')
    if not config.get_bin('ffmpeg'):
        if mime not in ['video/x-tivo-mpeg', 'video/mpeg', '']:
            message = (False, 'no ffmpeg')
        return message

    while True:
        vmessage = tivo_compatible_video(vInfo, tsn, mime)
        if not vmessage[0]:
            message = vmessage
            break

        amessage = tivo_compatible_audio(vInfo, inFile, tsn, mime)
        if not amessage[0]:
            message = amessage
            break

        cmessage = tivo_compatible_container(vInfo, inFile, mime)
        if not cmessage[0]:
            message = cmessage

        break

    debug('TRANSCODE=%s, %s, %s' % (['YES', 'NO'][message[0]],
                                           message[1], inFile))
    return message

def video_info(inFile, cache=True):
    vInfo = dict()
    fname = unicode(inFile, 'utf-8')
    mtime = os.stat(fname).st_mtime
    if cache:
        if inFile in info_cache and info_cache[inFile][0] == mtime:
            debug('CACHE HIT! %s' % inFile)
            return info_cache[inFile][1]

    vInfo['Supported'] = True

    ffmpeg_path = config.get_bin('ffmpeg')
    if not ffmpeg_path:
        if os.path.splitext(inFile)[1].lower() not in ['.mpg', '.mpeg',
                                                       '.vob', '.tivo']:
            vInfo['Supported'] = False
        vInfo.update({'millisecs': 0, 'vWidth': 704, 'vHeight': 480,
                      'rawmeta': {}})
        if cache:
            info_cache[inFile] = (mtime, vInfo)
        return vInfo

    if mswindows:
        fname = fname.encode('iso8859-1')
    cmd = [ffmpeg_path, '-i', fname]
    # Windows and other OS buffer 4096 and ffmpeg can output more than that.
    err_tmp = tempfile.TemporaryFile()
    ffmpeg = subprocess.Popen(cmd, stderr=err_tmp, stdout=subprocess.PIPE,
                              stdin=subprocess.PIPE)

    # wait configured # of seconds: if ffmpeg is not back give up
    wait = config.getFFmpegWait()
    debug('starting ffmpeg, will wait %s seconds for it to complete' % wait)
    for i in xrange(wait * 20):
        time.sleep(.05)
        if not ffmpeg.poll() == None:
            break

    if ffmpeg.poll() == None:
        kill(ffmpeg)
        vInfo['Supported'] = False
        if cache:
            info_cache[inFile] = (mtime, vInfo)
        return vInfo

    err_tmp.seek(0)
    output = err_tmp.read()
    err_tmp.close()
    debug('ffmpeg output=%s' % output)

    attrs = {'container': r'Input #0, ([^,]+),',
             'vCodec': r'Video: ([^, ]+)',             # video codec
             'aKbps': r'.*Audio: .+, (.+) (?:kb/s).*',     # audio bitrate
             'aCodec': r'.*Audio: ([^, ]+)',             # audio codec
             'aFreq': r'.*Audio: .+, (.+) (?:Hz).*',       # audio frequency
             'mapVideo': r'([0-9]+[.:]+[0-9]+).*: Video:.*'}  # video mapping

    for attr in attrs:
        rezre = re.compile(attrs[attr])
        x = rezre.search(output)
        if x:
            vInfo[attr] = x.group(1)
        else:
            if attr in ['container', 'vCodec']:
                vInfo[attr] = ''
                vInfo['Supported'] = False
            else:
                vInfo[attr] = None
            debug('failed at ' + attr)

    rezre = re.compile(r'.*Video: .+, (\d+)x(\d+)[, ].*')
    x = rezre.search(output)
    if x:
        vInfo['vWidth'] = int(x.group(1))
        vInfo['vHeight'] = int(x.group(2))
    else:
        vInfo['vWidth'] = ''
        vInfo['vHeight'] = ''
        vInfo['Supported'] = False
        debug('failed at vWidth/vHeight')

    rezre = re.compile(r'.*Video: .+, (.+) (?:fps|tb\(r\)|tbr).*')
    x = rezre.search(output)
    if x:
        vInfo['vFps'] = x.group(1)
        if '.' not in vInfo['vFps']:
            vInfo['vFps'] += '.00'

        # Allow override only if it is mpeg2 and frame rate was doubled 
        # to 59.94

        if vInfo['vCodec'] == 'mpeg2video' and vInfo['vFps'] != '29.97':
            # First look for the build 7215 version
            rezre = re.compile(r'.*film source: 29.97.*')
            x = rezre.search(output.lower())
            if x:
                debug('film source: 29.97 setting vFps to 29.97')
                vInfo['vFps'] = '29.97'
            else:
                # for build 8047:
                rezre = re.compile(r'.*frame rate differs from container ' +
                                   r'frame rate: 29.97.*')
                debug('Bug in VideoReDo')
                x = rezre.search(output.lower())
                if x:
                    vInfo['vFps'] = '29.97'
    else:
        vInfo['vFps'] = ''
        vInfo['Supported'] = False
        debug('failed at vFps')

    durre = re.compile(r'.*Duration: ([0-9]+):([0-9]+):([0-9]+)\.([0-9]+),')
    d = durre.search(output)

    if d:
        vInfo['millisecs'] = ((int(d.group(1)) * 3600 +
                               int(d.group(2)) * 60 +
                               int(d.group(3))) * 1000 +
                              int(d.group(4)) * (10 ** (3 - len(d.group(4)))))
    else:
        vInfo['millisecs'] = 0

    # get bitrate of source for tivo compatibility test.
    rezre = re.compile(r'.*bitrate: (.+) (?:kb/s).*')
    x = rezre.search(output)
    if x:
        vInfo['kbps'] = x.group(1)
    else:
        # Fallback method of getting video bitrate
        # Sample line:  Stream #0.0[0x1e0]: Video: mpeg2video, yuv420p,
        #               720x480 [PAR 32:27 DAR 16:9], 9800 kb/s, 59.94 tb(r)
        rezre = re.compile(r'.*Stream #0\.0\[.*\]: Video: mpeg2video, ' +
                           r'\S+, \S+ \[.*\], (\d+) (?:kb/s).*')
        x = rezre.search(output)
        if x:
            vInfo['kbps'] = x.group(1)
        else:
            vInfo['kbps'] = None
            debug('failed at kbps')

    # get par.
    rezre = re.compile(r'.*Video: .+PAR ([0-9]+):([0-9]+) DAR [0-9:]+.*')
    x = rezre.search(output)
    if x and x.group(1) != "0" and x.group(2) != "0":
        vInfo['par1'] = x.group(1) + ':' + x.group(2)
        vInfo['par2'] = float(x.group(1)) / float(x.group(2))
    else:
        vInfo['par1'], vInfo['par2'] = None, None
 
    # get dar.
    rezre = re.compile(r'.*Video: .+DAR ([0-9]+):([0-9]+).*')
    x = rezre.search(output)
    if x and x.group(1) != "0" and x.group(2) != "0":
        vInfo['dar1'] = x.group(1) + ':' + x.group(2)
    else:
        vInfo['dar1'] = None

    # get Audio Stream mapping.
    rezre = re.compile(r'([0-9]+[.:]+[0-9]+)(.*): Audio:.*')
    x = rezre.search(output)
    amap = []
    if x:
        for x in rezre.finditer(output):
            amap.append(x.groups())
    else:
        amap.append(('', ''))
        debug('failed at mapAudio')
    vInfo['mapAudio'] = amap

    vInfo['par'] = None

    # get Metadata dump (newer ffmpeg).
    lines = output.split('\n')
    rawmeta = {}
    flag = False

    for line in lines:
        if line.startswith('  Metadata:'):
            flag = True
        else:
            if flag:
                if line.startswith('  Duration:'):
                    flag = False
                else:
                    key, value = [x.strip() for x in line.split(':', 1)]
                    try:
                        value = value.decode('utf-8')
                    except:
                        if sys.platform == 'darwin':
                            value = value.decode('macroman')
                        else:
                            value = value.decode('iso8859-1')
                    rawmeta[key] = [value]

    vInfo['rawmeta'] = rawmeta

    data = metadata.from_text(inFile)
    for key in data:
        if key.startswith('Override_'):
            vInfo['Supported'] = True
            if key.startswith('Override_mapAudio'):
                audiomap = dict(vInfo['mapAudio'])
                stream = key.replace('Override_mapAudio', '').strip()
                if stream in audiomap:
                    newaudiomap = (stream, data[key])
                    audiomap.update([newaudiomap])
                    vInfo['mapAudio'] = sorted(audiomap.items(),
                                               key=lambda (k,v): (k,v))
            elif key.startswith('Override_millisecs'):
                vInfo[key.replace('Override_', '')] = int(data[key])
            else:
                vInfo[key.replace('Override_', '')] = data[key]

    if cache:
        info_cache[inFile] = (mtime, vInfo)
    debug("; ".join(["%s=%s" % (k, v) for k, v in vInfo.items()]))
    return vInfo

def audio_check(inFile, tsn):
    cmd_string = ('-y -vcodec mpeg2video -r 29.97 -b 1000k -acodec copy ' +
                  select_audiolang(inFile, tsn) + ' -t 00:00:01 -f vob -')
    fname = unicode(inFile, 'utf-8')
    if mswindows:
        fname = fname.encode('iso8859-1')
    cmd = [config.get_bin('ffmpeg'), '-i', fname] + cmd_string.split()
    ffmpeg = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    fd, testname = tempfile.mkstemp()
    testfile = os.fdopen(fd, 'wb')
    try:
        shutil.copyfileobj(ffmpeg.stdout, testfile)
    except:
        kill(ffmpeg)
        testfile.close()
        aKbps = None
    else:
        testfile.close()
        aKbps = video_info(testname, False)['aKbps']
    os.remove(testname)
    return aKbps

def supported_format(inFile):
    if video_info(inFile)['Supported']:
        return True
    else:
        debug('FALSE, file not supported %s' % inFile)
        return False

def kill(popen):
    debug('killing pid=%s' % str(popen.pid))
    if mswindows:
        win32kill(popen.pid)
    else:
        import os, signal
        for i in xrange(3):
            debug('sending SIGTERM to pid: %s' % popen.pid)
            os.kill(popen.pid, signal.SIGTERM)
            time.sleep(.5)
            if popen.poll() is not None:
                debug('process %s has exited' % popen.pid)
                break
        else:
            while popen.poll() is None:
                debug('sending SIGKILL to pid: %s' % popen.pid)
                os.kill(popen.pid, signal.SIGKILL)
                time.sleep(.5)

def win32kill(pid):
    import ctypes
    handle = ctypes.windll.kernel32.OpenProcess(1, False, pid)
    ctypes.windll.kernel32.TerminateProcess(handle, -1)
    ctypes.windll.kernel32.CloseHandle(handle)

def gcd(a, b):
    while b:
        a, b = b, a % b
    return a
