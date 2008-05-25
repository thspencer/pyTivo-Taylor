import subprocess, shutil, os, re, sys, tempfile, ConfigParser, time, lrucache, math
import config
import logging
from plugin import GetPlugin

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
    if tivo_compatable(inFile, tsn)[0]:
        logger.debug('%s is tivo compatible' % inFile)
        f = file(inFile, 'rb')
        shutil.copyfileobj(f, outFile)
        f.close()
    else:
        logger.debug('%s is not tivo compatible' % inFile)
        transcode(False, inFile, outFile, tsn)

def transcode(isQuery, inFile, outFile, tsn=''):

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
    settings['audio_codec'] = select_audiocodec(isQuery, inFile, tsn)
    settings['audio_lang'] = select_audiolang(inFile, tsn)
    settings['ffmpeg_pram'] = select_ffmpegprams(tsn)
    settings['format'] = select_format(tsn)

    if isQuery:
        return settings

    cmd_string = config.getFFmpegTemplate(tsn) % settings

    cmd = [ffmpeg_path(), '-i', inFile] + cmd_string.split()
    logging.debug('transcoding to tivo model '+tsn[:3]+' using ffmpeg command:')
    logging.debug(' '.join(cmd))
    ffmpeg = subprocess.Popen(cmd, bufsize=512*1024, stdout=subprocess.PIPE)

    try:
        shutil.copyfileobj(ffmpeg.stdout, outFile)
    except:
        kill(ffmpeg.pid)

def select_audiocodec(isQuery, inFile, tsn = ''):
    # Default, compatible with all TiVo's
    codec = 'ac3'
    vInfo =  video_info(inFile)
    codectype = vInfo['vCodec']
    if config.getAudioCodec(tsn) == None:
        if vInfo['aCodec'] in ('ac3', 'liba52', 'mp2'):
            if vInfo['aKbps'] == None:
                if not isQuery:
                    cmd_string = '-y -vcodec mpeg2video -r 29.97 -b 1000k -acodec copy '+\
                                 select_audiolang(inFile, tsn)+' -t 00:00:01 -f vob -'
                    if video_check(inFile, cmd_string):
                        vInfo =  video_info(videotest)
                else:
                    codec = 'TBD'
            if not vInfo['aKbps'] == None and int(vInfo['aKbps']) <= config.getMaxAudioBR(tsn):
                # compatible codec and bitrate, do not reencode audio
                codec = 'copy'
    else:
        codec = config.getAudioCodec(tsn)
    copyts = ' -copyts'
    if (codec == 'copy' and config.getCopyTS(tsn).lower() == 'none' \
        and codectype == 'mpeg2video') or config.getCopyTS(tsn).lower() == 'false':
        copyts = ''
    return '-acodec '+codec+copyts

def select_audiofr(inFile, tsn):
    freq = '48000'  #default
    vInfo =  video_info(inFile)
    if not vInfo['aFreq'] == None and vInfo['aFreq'] in ('44100', '48000'):
        # compatible frequency
        freq = vInfo['aFreq']
    if config.getAudioFR(tsn) != None:
        freq = config.getAudioFR(tsn)
    return '-ar '+freq

def select_audioch(tsn):
    if config.getAudioCH(tsn) != None:
        return '-ac '+config.getAudioCH(tsn)
    return ''

def select_audiolang(inFile, tsn):
    vInfo =  video_info(inFile)
    if config.getAudioLang(tsn) != None and vInfo['mapVid'] != None:
        stream, l = vInfo['mapAud'][0]
        for s, l in vInfo['mapAud']:
            if config.getAudioLang(tsn) in s+l:
                stream = s
                break
        if not stream == '':        
            return '-map '+vInfo['mapVid']+' -map '+stream
    return ''

def select_videofps(inFile, tsn):
    vInfo =  video_info(inFile)
    fps = '-r 29.97'  #default
    if config.isHDtivo(tsn) and vInfo['vFps'] not in BAD_MPEG_FPS:
        fps = ' '
    if config.getVideoFPS(tsn) != None:
        fps = '-r '+config.getVideoFPS(tsn)
    return fps

def select_videocodec(tsn):
    codec = 'mpeg2video'  #default
    if config.getVideoCodec(tsn) != None:
        codec = config.getVideoCodec(tsn)
    return '-vcodec '+codec

def select_videobr(inFile, tsn):
    return '-b '+select_videostr(inFile, tsn)

def select_videostr(inFile, tsn):
    video_str = config.getVideoBR(tsn)
    if config.isHDtivo(tsn):
        vInfo =  video_info(inFile)
        if vInfo['kbps'] != None and config.getVideoPCT() > 0:
            video_percent = int(vInfo['kbps'])*10*config.getVideoPCT()
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

    vInfo =  video_info(inFile)

    logging.debug('tsn: %s' % tsn)

    aspect169 = config.get169Setting(tsn)

    logging.debug('aspect169:%s' % aspect169)

    optres = config.getOptres(tsn)

    logging.debug('optres:%s' % optres)

    if optres:
        optHeight = config.nearestTivoHeight(vInfo['vHeight'])
        optWidth = config.nearestTivoWidth(vInfo['vWidth'])
        if optHeight < TIVO_HEIGHT:
            TIVO_HEIGHT = optHeight
        if optWidth < TIVO_WIDTH:
            TIVO_WIDTH = optWidth

    d = gcd(vInfo['vHeight'],vInfo['vWidth'])
    ratio = (vInfo['vWidth']*100)/vInfo['vHeight']
    rheight, rwidth = vInfo['vHeight']/d, vInfo['vWidth']/d

    logger.debug('File=%s vCodec=%s vWidth=%s vHeight=%s vFps=%s millisecs=%s ratio=%s rheight=%s rwidth=%s TIVO_HEIGHT=%sTIVO_WIDTH=%s' % (inFile, vInfo['vCodec'], vInfo['vWidth'], vInfo['vHeight'], vInfo['vFps'], vInfo['millisecs'], ratio, rheight, rwidth, TIVO_HEIGHT, TIVO_WIDTH))

    multiplier16by9 = (16.0 * TIVO_HEIGHT) / (9.0 * TIVO_WIDTH)
    multiplier4by3  =  (4.0 * TIVO_HEIGHT) / (3.0 * TIVO_WIDTH)

    if config.isHDtivo(tsn) and not optres:
        if config.getPixelAR(0):
            if vInfo['par2'] == None:
                npar = config.getPixelAR(1)
            else:
                npar = vInfo['par2']
            # adjust for pixel aspect ratio, if set, because TiVo expects square pixels
            if npar<1.0:
                return ['-s', str(vInfo['vWidth']) + 'x' + str(int(math.ceil(vInfo['vHeight']/npar)))]
            elif npar>1.0:
                # FFMPEG expects width to be a multiple of two
                return ['-s', str(int(math.ceil(vInfo['vWidth']*npar/2.0)*2)) + 'x' + str(vInfo['vHeight'])]
        if vInfo['vHeight'] <= TIVO_HEIGHT:
            # pass all resolutions to S3, except heights greater than conf height
            return []
        # else, resize video.
    if (rwidth, rheight) in [(1, 1)] and vInfo['par1'] == '8:9':
        logger.debug('File + PAR is within 4:3.')
        return ['-aspect', '4:3', '-s', str(TIVO_WIDTH) + 'x' + str(TIVO_HEIGHT)]
    elif (rwidth, rheight) in [(4, 3), (10, 11), (15, 11), (59, 54), (59, 72), (59, 36), (59, 54)] or vInfo['dar1'] == '4:3':
        logger.debug('File is within 4:3 list.')
        return ['-aspect', '4:3', '-s', str(TIVO_WIDTH) + 'x' + str(TIVO_HEIGHT)]
    elif ((rwidth, rheight) in [(16, 9), (20, 11), (40, 33), (118, 81), (59, 27)] or vInfo['dar1'] == '16:9')\
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
                    endHeight = int(((TIVO_WIDTH*vInfo['vHeight'])/vInfo['vWidth']) * multiplier16by9)
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
                    endWidth = int((TIVO_HEIGHT*vInfo['vWidth'])/(vInfo['vHeight']*multiplier16by9))
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
                endHeight = int(((TIVO_WIDTH*vInfo['vHeight'])/vInfo['vWidth']) * multiplier)
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
            endWidth = int((TIVO_HEIGHT*vInfo['vWidth'])/(vInfo['vHeight']*multiplier4by3))
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
    vInfo =  video_info(inFile)

    while True:

        if (inFile[-5:]).lower() == '.tivo':
            message = True, 'TRANSCODE=NO, ends with .tivo.'
            break

        if not vInfo['vCodec'] == 'mpeg2video':
            #print 'Not Tivo Codec'
            message = False, 'TRANSCODE=YES, vCodec %s not compatible.' % vInfo['vCodec']
            break

        if os.path.splitext(inFile)[-1].lower() in ('.ts', '.mpv', '.tp', '.dvr-ms'):
            message = False, 'TRANSCODE=YES, ext %s not compatible.' % os.path.splitext(inFile)[-1]
            break

        if vInfo['aCodec'] == 'dca':
            message = False, 'TRANSCODE=YES, aCodec %s not compatible.' % vInfo['aCodec']
            break

        if vInfo['aCodec'] != None:
            if not vInfo['aKbps'] or int(vInfo['aKbps']) > config.getMaxAudioBR(tsn):
                message = False, 'TRANSCODE=YES, %s kbps exceeds max audio bitrate.' % vInfo['aKbps']
                break

        if vInfo['kbps'] != None:
            abit = max('0', vInfo['aKbps'])
            if int(vInfo['kbps'])-int(abit) > config.strtod(config.getMaxVideoBR())/1000:
                message = False, 'TRANSCODE=YES, %s kbps exceeds max video bitrate.' % vInfo['kbps']
                break
        else:
            message = False, 'TRANSCODE=YES, %s kbps not supported.' % vInfo['kbps']
            break

        stream, l = vInfo['mapAud'][0]
        if stream != select_audiolang(inFile, tsn)[-3:]:
            message = False, 'TRANSCODE=YES, %s preferred audio track exists.' % config.getAudioLang(tsn)
            break

        if config.isHDtivo(tsn):
            if vInfo['par2'] != 1.0:
                if config.getPixelAR(0):
                    if vInfo['par2'] != None or config.getPixelAR(1) != 1.0:
                        message = False, 'TRANSCODE=YES, %s not correct PAR.' % vInfo['par2']
                        break
            message = True, 'TRANSCODE=NO, HD Tivo detected, skipping remaining tests.'
            break
        
        if not vInfo['vFps'] == '29.97':
            #print 'Not Tivo fps'
            message = False, 'TRANSCODE=YES, %s vFps, should be 29.97.' % vInfo['vFps']
            break
        
        if (config.get169Blacklist(tsn) and not config.get169Setting(tsn))\
            or (config.get169Letterbox(tsn) and config.get169Setting(tsn)):
            if vInfo['dar1'] == None or not vInfo['dar1'] in ('4:3', '8:9'):
                message = False, 'TRANSCODE=YES, DAR %s not supported by BLACKLIST_169 tivos.' % vInfo['dar1']
                break

        for mode in supportedModes:
            if (mode[0], mode[1]) == (vInfo['vWidth'], vInfo['vHeight']):
                message = True, 'TRANSCODE=NO, %s x %s is valid.' % (vInfo['vWidth'], vInfo['vHeight'])
                break
            #print 'Not Tivo dimensions'
            message = False, 'TRANSCODE=YES, %s x %s not in supported modes.' % (vInfo['vWidth'], vInfo['vHeight'])
        break

    logger.debug('%s, %s' % (message, inFile))
    return message


def video_info(inFile):
    vInfo = dict()
    mtime = os.stat(inFile).st_mtime
    if inFile != videotest:
        if inFile in info_cache and info_cache[inFile][0] == mtime:
            logging.debug('CACHE HIT! %s' % inFile)
            return info_cache[inFile][1]

    vInfo['Supported'] = True

    if (inFile[-5:]).lower() == '.tivo':
        vInfo['millisecs'] = 0
        info_cache[inFile] = (mtime, vInfo)
        logger.debug('VALID, ends in .tivo. %s' % inFile)
        return vInfo
    
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
        vInfo['Supported'] = False
        info_cache[inFile] = (mtime, vInfo)
        return vInfo

    err_tmp.seek(0) 
    output = err_tmp.read() 
    err_tmp.close() 
    logging.debug('ffmpeg output=%s' % output)

    rezre = re.compile(r'.*Video: ([^,]+),.*')
    x = rezre.search(output)
    if x:
        vInfo['vCodec'] = x.group(1)
    else:
        vInfo['vCodec'] = ''
        vInfo['Supported'] = False
        logger.debug('failed at vCodec')

    rezre = re.compile(r'.*Video: .+, (\d+)x(\d+)[, ].*')
    x = rezre.search(output)
    if x:
        vInfo['vWidth'] = int(x.group(1))
        vInfo['vHeight'] = int(x.group(2))
    else:
        vInfo['vWidth'] = ''
        vInfo['vHeight'] = ''
        vInfo['Supported'] = False
        logger.debug('failed at vWidth/vHeight')

    rezre = re.compile(r'.*Video: .+, (.+) (?:fps|tb).*')
    x = rezre.search(output)
    if x:
        vInfo['vFps'] = x.group(1)
        # Allow override only if it is mpeg2 and frame rate was doubled to 59.94
        if (not vInfo['vFps'] == '29.97') and (vInfo['vCodec'] == 'mpeg2video'):
            # First look for the build 7215 version
            rezre = re.compile(r'.*film source: 29.97.*')
            x = rezre.search(output.lower() )
            if x:
                logger.debug('film source: 29.97 setting vFps to 29.97')
                vInfo['vFps'] = '29.97'
            else:
                # for build 8047:
                rezre = re.compile(r'.*frame rate differs from container frame rate: 29.97.*')
                logger.debug('Bug in VideoReDo')
                x = rezre.search(output.lower() )
                if x:
                    vInfo['vFps'] = '29.97'
    else:
        vInfo['vFps'] = ''
        vInfo['Supported'] = False
        logger.debug('failed at vFps')

    durre = re.compile(r'.*Duration: ([0-9]+):([0-9]+):([0-9]+)\.([0-9]+),')
    d = durre.search(output)
    if d:
        vInfo['millisecs'] = ((int(d.group(1))*3600) + (int(d.group(2))*60) + int(d.group(3)))*1000 + (int(d.group(4))*100)
    else:
        vInfo['millisecs'] = 0

    #get bitrate of source for tivo compatibility test.
    rezre = re.compile(r'.*bitrate: (.+) (?:kb/s).*')
    x = rezre.search(output)
    if x:
        vInfo['kbps'] = x.group(1)
    else:
        vInfo['kbps'] = None
        logger.debug('failed at kbps')

    #get audio bitrate of source for tivo compatibility test.
    rezre = re.compile(r'.*Audio: .+, (.+) (?:kb/s).*')
    x = rezre.search(output)
    if x:
        vInfo['aKbps'] = x.group(1)
    else:
        vInfo['aKbps'] = None
        logger.debug('failed at aKbps')

    #get audio codec of source for tivo compatibility test.
    rezre = re.compile(r'.*Audio: ([^,]+),.*')
    x = rezre.search(output)
    if x:
        vInfo['aCodec'] = x.group(1)
    else:
        vInfo['aCodec'] = None
        logger.debug('failed at aCodec')

    #get audio frequency of source for tivo compatibility test.
    rezre = re.compile(r'.*Audio: .+, (.+) (?:Hz).*')
    x = rezre.search(output)
    if x:
        vInfo['aFreq'] = x.group(1)
    else:
        vInfo['aFreq'] = None
        logger.debug('failed at aFreq')

    #get par.
    rezre = re.compile(r'.*Video: .+PAR ([0-9]+):([0-9]+) DAR [0-9:]+.*')
    x = rezre.search(output)
    if x and x.group(1)!="0" and x.group(2)!="0":
        vInfo['par1'], vInfo['par2'] = x.group(1)+':'+x.group(2), float(x.group(1))/float(x.group(2))
    else:
        vInfo['par1'], vInfo['par2'] = None, None
 
    #get dar.
    rezre = re.compile(r'.*Video: .+DAR ([0-9]+):([0-9]+).*')
    x = rezre.search(output)
    if x and x.group(1)!="0" and x.group(2)!="0":
        vInfo['dar1'], vInfo['dar2'] = x.group(1)+':'+x.group(2), float(x.group(1))/float(x.group(2))
    else:
        vInfo['dar1'], vInfo['dar2'] = None, None

    #get Video Stream mapping.
    rezre = re.compile(r'([0-9]+\.[0-9]+).*: Video:.*')
    x = rezre.search(output)
    if x:
        vInfo['mapVid'] = x.group(1)
    else:
        vInfo['mapVid'] = None
        logger.debug('failed at mapVid')


    #get Audio Stream mapping.
    rezre = re.compile(r'([0-9]+\.[0-9]+)(.*): Audio:.*')
    x = rezre.search(output)
    amap = []
    if x:
        for x in rezre.finditer(output):
            amap.append(x.groups())
    else:
        amap.append(('', ''))
        logger.debug('failed at mapAud')
    vInfo['mapAud'] = amap


    videoPlugin = GetPlugin('video')
    metadata = videoPlugin.getMetadataFromTxt(inFile)

    for key in metadata:
        if key.startswith('Override_'):
            vInfo['Supported'] = True
            vInfo[key.replace('Override_','')] = metadata[key]

    info_cache[inFile] = (mtime, vInfo)
    logger.debug("; ".join(["%s=%s" % (k, v) for k, v in vInfo.items()]))
    return vInfo

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
    if video_info(inFile)['Supported']:
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

