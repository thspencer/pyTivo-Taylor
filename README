---Description

pyTivo lets you stream most videos from your PC to your unhacked tivo. 
It uses the HMO server protocol. It will guess if your video is 4:3 or 
16:9 and pad your video if it thinks it is needed. It will not transcode 
an mpeg that is supported by your tivo.

---Requirements

OS = Anything that will run python and ffmpeg, which I think is 
anything. Known to work on Linux, Mac OS X and Windows.

Python - http://www.python.org/download/
- You need at least version 2.5 of python

pywin32 (only to install as a service) - 
http://sourceforge.net/project/showfiles.php?group_id=78018&package_id=79063
- Windows users only and only if you intend to install as a service

---Usage

You need to edit pyTivo.conf in 3 places

1. ffmpeg=
2. [<name of share>]
3. path=

ffmpeg should be the full path to ffmpeg including filename. path is the 
absolute path to your media.

run pyTivo.py

---To install as a service in Windows

run pyTivoService.py --startup auto install

---To remove service

run pyTivoService.py remove

---Notes
pyTivo was created by Jason Michalski ("armooo"). Contributors include 
Kevin R. Keegan, William McBrine, and Terry Mound ("wgw").
