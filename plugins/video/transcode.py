import subprocess, shutil, os, re, sys, tempfile, ConfigParser, time, lrucache, math
import config
import logging

logger = logging.getLogger('pyTivo.video.transcode')

info_cache = lrucache.LRUCache(1000)
videotest = os.path.join(os.path.dirname(__file__), 'videotest.mpg')

BAD_MPEG_FPS = ['15.00']

def ffmpeg_path():
    return config.get('Server', 'ffmpeg')

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

def output_video(inFile, outFile, tsn=''):
    if tivo_compatable(inFile, tsn):
        logger.debug('%s is tivo compatible' % inFile)
        f = file(inFile, 'rb')
        shutil.copyfileobj(f, outFile)
        f.close()
    else:
        logger.debug('%s is not tivo compatible' % inFile)
        transcode(inFile, outFile, tsn)

def transcode(inFile, outFile, tsn=''):

    settings = {}
    settings['video_codec'] = select_videocodec(tsn)
    settings['video_br'] = select_videobr(inFile, tsn)
    settings['video_fps'] = select_videofps(inFile, tsn)
    settings['max_video_br'] = select_maxvideobr()
    settings['buff_size'] = select_buffsize()
    settings['aspect_ratio'] = ' '.join(select_aspect(inFile, tsn))
    settings['audio_br'] = select_audiobr(tsn)
    settings['audio_fr'] = select_audiofr(inFile, tsn)
    settings['audio_ch'] = select_audioch(tsn)
    settings['audio_codec'] = select_audiocodec(inFile, tsn)
    settings['ffmpeg_pram'] = select_ffmpegprams(tsn)
    settings['format'] = select_format(tsn)

    cmd_string = config.getFFmpegTemplate(tsn) % settings

    cmd = [ffmpeg_path(), '-i', inFile] + cmd_string.split()
    logging.debug('transcoding to tivo model '+tsn[:3]+' using ffmpeg command:')
    logging.debug(' '.join(cmd))
    ffmpeg = subprocess.Popen(cmd, bufsize=512*1024, stdout=subprocess.PIPE)

    try:
        shutil.copyfileobj(ffmpeg.stdout, outFile)
    except:
        kill(ffmpeg.pid)

def select_audiocodec(inFile, tsn = ''):
    # Default, compatible with all TiVo's
    codec = 'ac3'
    type, width, height, fps, millisecs, kbps, akbps, acodec, afreq, par1, par2, dar1, dar2 =  video_info(inFile)
    if config.getAudioCodec(tsn) == None:
        if acodec in ('ac3', 'liba52', 'mp2'):
            if akbps == None:
                cmd_string = '-y -vcodec mpeg2video -r 29.97 -b 1000k -acodec copy -t 00:00:01 -f vob -'
                if video_check(inFile, cmd_string):
                    typetest, width, height, fps, millisecs, kbps, akbps, acodec, afreq, par1, par2, dar1, dar2 =  video_info(videotest)
            if not akbps == None and int(akbps) <= config.getMaxAudioBR(tsn):
                # compatible codec and bitrate, do not reencode audio
                codec = 'copy'
    else:
        codec = config.getAudioCodec(tsn)
    copyts = ' -copyts'
    if (codec == 'copy' and config.getCopyTS(tsn).lower() == 'none' \
        and type == 'mpeg2video') or config.getCopyTS(tsn).lower() == 'false':
        copyts = ''
    return '-acodec '+codec+copyts

def select_audiofr(inFile, tsn):
    freq = '48000'  #default
    type, width, height, fps, millisecs, kbps, akbps, acodec, afreq, par1, par2, dar1, dar2 =  video_info(inFile)
    if not afreq == None and afreq in ('44100', '48000'):
        # compatible frequency
        freq = afreq
    if config.getAudioFR(tsn) != None:
        freq = config.getAudioFR(tsn)
    return '-ar '+freq

def select_audioch(tsn):
    if config.getAudioCH(tsn) != None:
        return '-ac '+config.getAudioCH(tsn)
    return ''

def select_videofps(inFile, tsn):
    type, width, height, fps, millisecs, kbps, akbps, acodec, afreq, par1, par2, dar1, dar2 =  video_info(inFile)
    vfps = '-r 29.97'  #default
    if config.isHDtivo(tsn) and fps not in BAD_MPEG_FPS:
        vfps = ' '
    if config.getVideoFPS(tsn) != None:
        vfps = '-r '+config.getVideoFPS(tsn)
    return vfps

def select_videocodec(tsn):
    vcodec = 'mpeg2video'  #default
    if config.getVideoCodec(tsn) != None:
        vcodec = config.getVideoCodec(tsn)
    return '-vcodec '+vcodec

def select_videobr(inFile, tsn):
    return '-b '+select_videostr(inFile, tsn)

def select_videostr(inFile, tsn):
    video_str = config.getVideoBR(tsn)
    if config.isHDtivo(tsn):
        type, width, height, fps, millisecs, kbps, akbps, acodec, afreq, par1, par2, dar1, dar2 =  video_info(inFile)
        if kbps != None and config.getVideoPCT() > 0:
            video_percent = int(kbps)*10*config.getVideoPCT()
            video_bitrate = max(config.strtod(video_str), video_percent)
            video_str = str(int(min(config.strtod(config.getMaxVideoBR())*0.95, video_bitrate)))
    return video_str

def select_audiobr(tsn):
    return '-ab '+config.getAudioBR(tsn)

def select_maxvideobr():
    return '-maxrate '+config.getMaxVideoBR()

def select_buffsize():
    return '-bufsize '+config.getBuffSize()

def select_ffmpegprams(tsn):
    if config.getFFmpegPrams(tsn) != None:
        return config.getFFmpegPrams(tsn)
    return ''

def select_format(tsn):
    fmt = 'vob'
    if config.getFormat(tsn) != None:
        fmt = config.getFormat(tsn)
    return '-f '+fmt+' -'

def select_aspect(inFile, tsn = ''):
    TIVO_WIDTH = config.getTivoWidth(tsn)
    TIVO_HEIGHT = config.getTivoHeight(tsn)

    type, width, height, fps, millisecs, kbps, akbps, acodec, afreq, par1, par2, dar1, dar2 =  video_info(inFile)

    logging.debug('tsn: %s' % tsn)

    aspect169 = config.get169Setting(tsn)

    logging.debug('aspect169:%s' % aspect169)

    optres = config.getOptres(tsn)

    logging.debug('optres:%s' % optres)

    if optres:
        optHeight = config.nearestTivoHeight(height)
        optWidth = config.nearestTivoWidth(width)
        if optHeight < TIVO_HEIGHT:
            TIVO_HEIGHT = optHeight
        if optWidth < TIVO_WIDTH:
            TIVO_WIDTH = optWidth

    d = gcd(height,width)
    ratio = (width*100)/height
    rheight, rwidth = height/d, width/d

    logger.debug('File=%s Type=%s width=%s height=%s fps=%s millisecs=%s ratio=%s rheight=%s rwidth=%s TIVO_HEIGHT=%sTIVO_WIDTH=%s' % (inFile, type, width, height, fps, millisecs, ratio, rheight, rwidth, TIVO_HEIGHT, TIVO_WIDTH))

    multiplier16by9 = (16.0 * TIVO_HEIGHT) / (9.0 * TIVO_WIDTH)
    multiplier4by3  =  (4.0 * TIVO_HEIGHT) / (3.0 * TIVO_WIDTH)

    if config.isHDtivo(tsn) and not optres:
        if config.getPixelAR(0):
            if par2 == None:
                npar = config.getPixelAR(1)
            else:
                npar = par2
            # adjust for pixel aspect ratio, if set, because TiVo expects square pixels
            if npar<1.0:
                return ['-s', str(width) + 'x' + str(int(math.ceil(height/npar)))]
            elif npar>1.0:
                # FFMPEG expects width to be a multiple of two
                return ['-s', str(int(math.ceil(width*npar/2.0)*2)) + 'x' + str(height)]
        if height <= TIVO_HEIGHT:
            # pass all resolutions to S3, except heights greater than conf height
            return []
        # else, resize video.
    if (rwidth, rheight) in [(1, 1)] and par1 == '8:9':
        logger.debug('File + PAR is within 4:3.')
        return ['-aspect', '4:3', '-s', str(TIVO_WIDTH) + 'x' + str(TIVO_HEIGHT)]
    elif (rwidth, rheight) in [(4, 3), (10, 11), (15, 11), (59, 54), (59, 72), (59, 36), (59, 54)] or dar1 == '4:3':
        logger.debug('File is within 4:3 list.')
        return ['-aspect', '4:3', '-s', str(TIVO_WIDTH) + 'x' + str(TIVO_HEIGHT)]
    elif ((rwidth, rheight) in [(16, 9), (20, 11), (40, 33), (118, 81), (59, 27)] or dar1 == '16:9')\
         and (aspect169 or config.get169Letterbox(tsn)):
        logger.debug('File is within 16:9 list and 16:9 allowed.')
        if config.get169Blacklist(tsn) or (aspect169 and config.get169Letterbox(tsn)): 
            return ['-aspect', '4:3', '-s', str(TIVO_WIDTH) + 'x' + str(TIVO_HEIGHT)]
        else:
            return ['-aspect', '16:9', '-s', str(TIVO_WIDTH) + 'x' + str(TIVO_HEIGHT)]
    else:
        settings = []
        #If video is wider than 4:3 add top and bottom padding
        if (ratio > 133): #Might be 16:9 file, or just need padding on top and bottom
            if aspect169 and (ratio > 135): #If file would fall in 4:3 assume it is supposed to be 4:3
                if (ratio > 177):#too short needs padding top and bottom
                    endHeight = int(((TIVO_WIDTH*height)/width) * multiplier16by9)
                    settings.append('-aspect') 
                    if config.get169Blacklist(tsn) or config.get169Letterbox(tsn): 
                        settings.append('4:3') 
                    else: 
                        settings.append('16:9')
                    if endHeight % 2:
                        endHeight -= 1
                    if endHeight < TIVO_HEIGHT * 0.99:
                        settings.append('-s')
                        settings.append(str(TIVO_WIDTH) + 'x' + str(endHeight))

                        topPadding = ((TIVO_HEIGHT - endHeight)/2)
                        if topPadding % 2:
                            topPadding -= 1

                        settings.append('-padtop')
                        settings.append(str(topPadding))
                        bottomPadding = (TIVO_HEIGHT - endHeight) - topPadding
                        settings.append('-padbottom')
                        settings.append(str(bottomPadding))
                    else:   #if only very small amount of padding needed, then just stretch it
                        settings.append('-s')
                        settings.append(str(TIVO_WIDTH) + 'x' + str(TIVO_HEIGHT))
                    logger.debug('16:9 aspect allowed, file is wider than 16:9 padding top and bottom\n%s' % ' '.join(settings))
                else: #too skinny needs padding on left and right.
                    endWidth = int((TIVO_HEIGHT*width)/(height*multiplier16by9))
                    settings.append('-aspect')
                    if config.get169Blacklist(tsn) or config.get169Letterbox(tsn): 
                        settings.append('4:3') 
                    else: 
                        settings.append('16:9')
                    if endWidth % 2:
                        endWidth -= 1
                    if endWidth < (TIVO_WIDTH-10):
                        settings.append('-s')
                        settings.append(str(endWidth) + 'x' + str(TIVO_HEIGHT))

                        leftPadding = ((TIVO_WIDTH - endWidth)/2)
                        if leftPadding % 2:
                            leftPadding -= 1

                        settings.append('-padleft')
                        settings.append(str(leftPadding))
                        rightPadding = (TIVO_WIDTH - endWidth) - leftPadding
                        settings.append('-padright')
                        settings.append(str(rightPadding))
                    else: #if only very small amount of padding needed, then just stretch it
                        settings.append('-s')
                        settings.append(str(TIVO_WIDTH) + 'x' + str(TIVO_HEIGHT))
                    logger.debug('16:9 aspect allowed, file is narrower than 16:9 padding left and right\n%s' % ' '.join(settings))
            else: #this is a 4:3 file or 16:9 output not allowed
                multiplier = multiplier4by3
                settings.append('-aspect')
                if ratio > 135 and config.get169Letterbox(tsn):
                    settings.append('16:9')
                    multiplier = multiplier16by9
                else:
                    settings.append('4:3')
                endHeight = int(((TIVO_WIDTH*height)/width) * multiplier)
                if endHeight % 2:
                    endHeight -= 1
                if endHeight < TIVO_HEIGHT * 0.99:
                    settings.append('-s')
                    settings.append(str(TIVO_WIDTH) + 'x' + str(endHeight))

                    topPadding = ((TIVO_HEIGHT - endHeight)/2)
                    if topPadding % 2:
                        topPadding -= 1

                    settings.append('-padtop')
                    settings.append(str(topPadding))
                    bottomPadding = (TIVO_HEIGHT - endHeight) - topPadding
                    settings.append('-padbottom')
                    settings.append(str(bottomPadding))
                else:   #if only very small amount of padding needed, then just stretch it
                    settings.append('-s')
                    settings.append(str(TIVO_WIDTH) + 'x' + str(TIVO_HEIGHT))
                logging.debug('File is wider than 4:3 padding top and bottom\n%s' %  ' '.join(settings))

            return settings
        #If video is taller than 4:3 add left and right padding, this is rare. All of these files will always be sent in
        #an aspect ratio of 4:3 since they are so narrow.
        else:
            endWidth = int((TIVO_HEIGHT*width)/(height*multiplier4by3))
            settings.append('-aspect')
            settings.append('4:3')
            if endWidth % 2:
                endWidth -= 1
            if endWidth < (TIVO_WIDTH * 0.99):
                settings.append('-s')
                settings.append(str(endWidth) + 'x' + str(TIVO_HEIGHT))

                leftPadding = ((TIVO_WIDTH - endWidth)/2)
                if leftPadding % 2:
                    leftPadding -= 1

                settings.append('-padleft')
                settings.append(str(leftPadding))
                rightPadding = (TIVO_WIDTH - endWidth) - leftPadding
                settings.append('-padright')
                settings.append(str(rightPadding))
            else: #if only very small amount of padding needed, then just stretch it
                settings.append('-s')
                settings.append(str(TIVO_WIDTH) + 'x' + str(TIVO_HEIGHT))

            logger.debug('File is taller than 4:3 padding left and right\n%s' % ' '.join(settings))

            return settings

def tivo_compatable(inFile, tsn = ''):
    supportedModes = [[720, 480], [704, 480], [544, 480], [528, 480], [480, 480], [352, 480]]
    type, width, height, fps, millisecs, kbps, akbps, acodec, afreq, par1, par2, dar1, dar2 =  video_info(inFile)
    #print type, width, height, fps, millisecs, kbps, akbps, acodec

    if (inFile[-5:]).lower() == '.tivo':
        logger.debug('TRUE, ends with .tivo. %s' % inFile)
        return True

    if not type == 'mpeg2video':
        #print 'Not Tivo Codec'
        logger.debug('FALSE, type %s not mpeg2video. %s' % (type, inFile))
        return False

    if os.path.splitext(inFile)[-1].lower() in ('.ts', '.mpv', '.tp'):
        logger.debug('FALSE, ext %s not tivo compatible. %s' % (os.path.splitext(inFile)[-1], inFile))
        return False

    if acodec == 'dca':
        logger.debug('FALSE, acodec %s not supported. %s' % (acodec, inFile))
        return False

    if acodec != None:
        if not akbps or int(akbps) > config.getMaxAudioBR(tsn):
            logger.debug('FALSE, %s kbps exceeds max audio bitrate. %s' % (akbps, inFile))
            return False

    if kbps != None:
        abit = max('0', akbps)
        if int(kbps)-int(abit) > config.strtod(config.getMaxVideoBR())/1000:
            logger.debug('FALSE, %s kbps exceeds max video bitrate. %s' % (kbps, inFile))
            return False
    else:
        logger.debug('FALSE, %s kbps not supported. %s' % (kbps, inFile))
        return False

    if config.isHDtivo(tsn):
        if par2 != 1.0:
            if config.getPixelAR(0):
                if par2 != None or config.getPixelAR(1) != 1.0:
                    logger.debug('FALSE, %s not correct PAR, %s' % (par2, inFile))
                    return False
        logger.debug('TRUE, HD Tivo detected, skipping remaining tests %s' % inFile)
        return True

    if not fps == '29.97':
        #print 'Not Tivo fps'
        logger.debug('FALSE, %s fps, should be 29.97. %s' % (fps, inFile))
        return False

    if (config.get169Blacklist(tsn) and not config.get169Setting(tsn))\
        or (config.get169Letterbox(tsn) and config.get169Setting(tsn)):
        if dar1 == None or not dar1 in ('4:3', '8:9'):
            debug_write(__name__, fn_attr(), ['FALSE, DAR', dar1, 'not supported by BLACKLIST_169 tivos.', inFile])
            return False

    for mode in supportedModes:
        if (mode[0], mode[1]) == (width, height):
            logger.debug('TRUE, %s x %s is valid. %s' % (width, height, inFile))
            return True
    #print 'Not Tivo dimensions'
    logger.debug('FALSE, %s x %s not in supported modes. %s' % (width, height, inFile))
    return False

def video_info(inFile):
    mtime = os.stat(inFile).st_mtime
    if inFile != videotest:
        if inFile in info_cache and info_cache[inFile][0] == mtime:
            logging.debug('CACHE HIT! %s' % inFile)
            return info_cache[inFile][1]

    if (inFile[-5:]).lower() == '.tivo':
        info_cache[inFile] = (mtime, (True, True, True, True, True, True, True, True, True, True, True, True, True))
        logger.debug('VALID, ends in .tivo. %s' % inFile)
        return True, True, True, True, True, True, True, True, True, True, True, True, True
    
    cmd = [ffmpeg_path(), '-i', inFile ]
    # Windows and other OS buffer 4096 and ffmpeg can output more than that.
    err_tmp = tempfile.TemporaryFile()
    ffmpeg = subprocess.Popen(cmd, stderr=err_tmp, stdout=subprocess.PIPE, stdin=subprocess.PIPE)

    # wait 10 sec if ffmpeg is not back give up
    for i in xrange(200):
        time.sleep(.05)
        if not ffmpeg.poll() == None:
            break

    if ffmpeg.poll() == None:
        kill(ffmpeg.pid)
        info_cache[inFile] = (mtime, (None, None, None, None, None, None, None, None, None, None, None, None, None))
        return None, None, None, None, None, None, None, None, None, None, None, None, None

    err_tmp.seek(0) 
    output = err_tmp.read() 
    err_tmp.close() 
    logging.debug('ffmpeg output=%s' % output)

    rezre = re.compile(r'.*Video: ([^,]+),.*')
    x = rezre.search(output)
    if x:
        codec = x.group(1)
    else:
        info_cache[inFile] = (mtime, (None, None, None, None, None, None, None, None, None, None, None, None, None))
        logging.debug('failed at video codec')
        return None, None, None, None, None, None, None, None, None, None, None, None, None

    rezre = re.compile(r'.*Video: .+, (\d+)x(\d+)[, ].*')
    x = rezre.search(output)
    if x:
        width = int(x.group(1))
        height = int(x.group(2))
    else:
        info_cache[inFile] = (mtime, (None, None, None, None, None, None, None, None, None, None, None, None, None))
        logger.debug('failed at width/height')
        return None, None, None, None, None, None, None, None, None, None, None, None, None

    rezre = re.compile(r'.*Video: .+, (.+) (?:fps|tb).*')
    x = rezre.search(output)
    if x:
        fps = x.group(1)
    else:
        info_cache[inFile] = (mtime, (None, None, None, None, None, None, None, None, None, None, None, None, None))
        logging.debug('failed at fps')
        return None, None, None, None, None, None, None, None, None, None, None, None, None

    # Allow override only if it is mpeg2 and frame rate was doubled to 59.94
    if (not fps == '29.97') and (codec == 'mpeg2video'):
        # First look for the build 7215 version
        rezre = re.compile(r'.*film source: 29.97.*')
        x = rezre.search(output.lower() )
        if x:
            logger.debug('film source: 29.97 setting fps to 29.97')
            fps = '29.97'
        else:
            # for build 8047:
            rezre = re.compile(r'.*frame rate differs from container frame rate: 29.97.*')
            logger.debug('Bug in VideoReDo')
            x = rezre.search(output.lower() )
            if x:
                fps = '29.97'

    durre = re.compile(r'.*Duration: (.{2}):(.{2}):(.{2})\.(.),')
    d = durre.search(output)
    if d:
        millisecs = ((int(d.group(1))*3600) + (int(d.group(2))*60) + int(d.group(3)))*1000 + (int(d.group(4))*100)
    else:
        millisecs = 0

    #get bitrate of source for tivo compatibility test.
    rezre = re.compile(r'.*bitrate: (.+) (?:kb/s).*')
    x = rezre.search(output)
    if x:
        kbps = x.group(1)
    else:
        kbps = None
        logger.debug('failed at kbps')

    #get audio bitrate of source for tivo compatibility test.
    rezre = re.compile(r'.*Audio: .+, (.+) (?:kb/s).*')
    x = rezre.search(output)
    if x:
        akbps = x.group(1)
    else:
        akbps = None
        logger.debug('failed at akbps')

    #get audio codec of source for tivo compatibility test.
    rezre = re.compile(r'.*Audio: ([^,]+),.*')
    x = rezre.search(output)
    if x:
        acodec = x.group(1)
    else:
        acodec = None
        logger.debug('failed at acodec')

    #get audio frequency of source for tivo compatibility test.
    rezre = re.compile(r'.*Audio: .+, (.+) (?:Hz).*')
    x = rezre.search(output)
    if x:
        afreq = x.group(1)
    else:
        afreq = None
        logger.debug('failed at afreq')

    #get par.
    rezre = re.compile(r'.*Video: .+PAR ([0-9]+):([0-9]+) DAR [0-9:]+.*')
    x = rezre.search(output)
    if x and x.group(1)!="0" and x.group(2)!="0":
        par1, par2 = x.group(1)+':'+x.group(2), float(x.group(1))/float(x.group(2))
    else:
        par1, par2 = None, None
 
    #get dar.
    rezre = re.compile(r'.*Video: .+DAR ([0-9]+):([0-9]+).*')
    x = rezre.search(output)
    if x and x.group(1)!="0" and x.group(2)!="0":
        dar1, dar2 = x.group(1)+':'+x.group(2), float(x.group(1))/float(x.group(2))
    else:
        dar1, dar2 = None, None
 
    info_cache[inFile] = (mtime, (codec, width, height, fps, millisecs, kbps, akbps, acodec, afreq, par1, par2, dar1, dar2))
    logger.debug('Codec=%s width=%s height=%s fps=%s millisecs=%s kbps=%s akbps=%s acodec=%s afreq=%s par=%s %s dar=%s %s' %
        (codec, width, height, fps, millisecs, kbps, akbps, acodec, afreq, par1, par2, dar1, dar2))
    return codec, width, height, fps, millisecs, kbps, akbps, acodec, afreq, par1, par2, dar1, dar2

def video_check(inFile, cmd_string):
    cmd = [ffmpeg_path(), '-i', inFile] + cmd_string.split()
    ffmpeg = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    try:
        shutil.copyfileobj(ffmpeg.stdout, open(videotest, 'wb'))
        return True
    except:
        kill(ffmpeg.pid)
        return False

def supported_format(inFile):
    if video_info(inFile)[0]:
        return True
    else:
        logger.debug('FALSE, file not supported %s' % inFile)
        return False

def kill(pid):
    logger.debug('killing pid=%s' % str(pid))
    if mswindows:
        win32kill(pid)
    else:
        import os, signal
        os.kill(pid, signal.SIGTERM)

def win32kill(pid):
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(1, False, pid)
        ctypes.windll.kernel32.TerminateProcess(handle, -1)
        ctypes.windll.kernel32.CloseHandle(handle)

def gcd(a,b):
    while b:
        a, b = b, a % b
    return a

