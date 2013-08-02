"""
    Quicktime/MP4 Fast Start
    ------------------------
    Enable streaming and pseudo-streaming of Quicktime and MP4 files by
    moving metadata and offset information to the front of the file.

    This program is based on qt-faststart.c from the ffmpeg project, which is
    released into the public domain, as well as ISO 14496-12:2005 (the official
    spec for MP4), which can be obtained from the ISO or found online.

    The goals of this project are to run anywhere without compilation (in
    particular, many Windows and Mac OS X users have trouble getting
    qt-faststart.c compiled), to run about as fast as the C version, to be more
    user friendly, and to use less actual lines of code doing so.

    Features
    --------

        * Works everywhere Python can be installed
        * Handles both 32-bit (stco) and 64-bit (co64) atoms
        * Handles any file where the mdat atom is before the moov atom
        * Preserves the order of other atoms
        * Can replace the original file (if given no output file)

    History
    -------
     * 2013-01-28: Support strange zero-name, zero-length atoms, re-license
                   under the MIT license, version bump to 1.7
     * 2010-02-21: Add support for final mdat atom with zero size, patch by
                   Dmitry Simakov <basilio AT j-vista DOT ru>, version bump
                   to 1.4.
     * 2009-11-05: Add --sample option. Version bump to 1.3.
     * 2009-03-13: Update to be more library-friendly by using logging module,
                   rename fast_start => process, version bump to 1.2
     * 2008-10-04: Bug fixes, support multiple atoms of the same type, 
                   version bump to 1.1
     * 2008-09-02: Initial release

    License
    -------

    Copyright (C) 2008 - 2013  Daniel G. Taylor <dan@programmer-art.org>

    Permission is hereby granted, free of charge, to any person 
    obtaining a copy of this software and associated documentation files 
    (the "Software"), to deal in the Software without restriction, 
    including without limitation the rights to use, copy, modify, merge, 
    publish, distribute, sublicense, and/or sell copies of the Software, 
    and to permit persons to whom the Software is furnished to do so, 
    subject to the following conditions:

    The above copyright notice and this permission notice shall be 
    included in all copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, 
    EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF 
    MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND 
    NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS 
    BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN 
    ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN 
    CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE 
    SOFTWARE.
"""

import logging
import os
import struct

from StringIO import StringIO

VERSION = "1.7wjm3"
CHUNK_SIZE = 8192

log = logging.getLogger('pyTivo.video.qt-faststart')

count = 0

class FastStartException(Exception):
    pass

def read_atom(datastream):
    """
        Read an atom and return a tuple of (size, type) where size is the size
        in bytes (including the 8 bytes already read) and type is a "fourcc"
        like "ftyp" or "moov".
    """
    return struct.unpack(">L4s", datastream.read(8))

def get_index(datastream):
    """
        Return an index of top level atoms, their absolute byte-position in the
        file and their size in a list:

        index = [
            ("ftyp", 0, 24),
            ("moov", 25, 2658),
            ("free", 2683, 8),
            ...
        ]

        The tuple elements will be in the order that they appear in the file.
    """
    index = []

    log.debug("Getting index of top level atoms...")

    # Read atoms until we catch an error
    while(datastream):
        try:
            skip = 8
            atom_size, atom_type = read_atom(datastream)
            if atom_size == 1:
                atom_size = struct.unpack(">Q", datastream.read(8))[0]
                skip = 16
            log.debug("%s: %s" % (atom_type, atom_size))
        except:
            break

        index.append((atom_type, datastream.tell() - skip, atom_size))

        if atom_size == 0:
            if atom_type == "mdat":
                # Some files may end in mdat with no size set, which
                # generally means to seek to the end of the file. We can
                # just stop indexing as no more entries will be found!
                break
            else:
                # Weird, but just continue to try to find more atoms
                atom_size = skip

        datastream.seek(atom_size - skip, os.SEEK_CUR)

    # Make sure the atoms we need exist
    top_level_atoms = set([item[0] for item in index])
    for key in ["moov", "mdat"]:
        if key not in top_level_atoms:
            log.error("%s atom not found, is this a valid MOV/MP4 file?" % key)
            raise FastStartException()

    return index

def find_atoms(size, datastream):
    """
        This function is a generator that will yield either "stco" or "co64"
        when either atom is found. datastream can be assumed to be 8 bytes
        into the stco or co64 atom when the value is yielded.

        It is assumed that datastream will be at the end of the atom after
        the value has been yielded and processed.

        size is the number of bytes to the end of the atom in the datastream.
    """
    stop = datastream.tell() + size

    while datastream.tell() < stop:
        try:
            atom_size, atom_type = read_atom(datastream)
        except:
            log.exception("Error reading next atom!")
            raise FastStartException()

        if atom_type in ["trak", "mdia", "minf", "stbl"]:
            # Known ancestor atom of stco or co64, search within it!
            for atype in find_atoms(atom_size - 8, datastream):
                yield atype
        elif atom_type in ["stco", "co64"]:
            yield atom_type
        else:
            # Ignore this atom, seek to the end of it.
            datastream.seek(atom_size - 8, os.SEEK_CUR)

def output(outfile, skip, data):
    global count
    length = len(data)
    if count + length > skip:
        if skip > count:
            data = data[skip - count:]
        outfile.write(data)
    count += length

def process(datastream, outfile, skip=0):
    """
        Convert a Quicktime/MP4 file for streaming by moving the metadata to
        the front of the file. This method writes a new file.
    """

    global count
    count = 0

    # Get the top level atom index
    index = get_index(datastream)

    mdat_pos = 999999
    free_size = 0

    # Make sure moov occurs AFTER mdat, otherwise no need to run!
    for atom, pos, size in index:
        # The atoms are guaranteed to exist from get_index above!
        if atom == "moov":
            moov_pos = pos
            moov_size = size
        elif atom == "mdat":
            mdat_pos = pos
        elif atom == "free" and pos < mdat_pos:
            # This free atom is before the mdat!
            free_size += size
            log.info("Removing free atom at %d (%d bytes)" % (pos, size))
        elif atom == "\x00\x00\x00\x00" and pos < mdat_pos:
            # This is some strange zero atom with incorrect size
            free_size += 8
            log.info("Removing strange zero atom at %s (8 bytes)" % pos)
 
    # Offset to shift positions
    offset = moov_size - free_size

    if moov_pos < mdat_pos:
        # moov appears to be in the proper place, don't shift by moov size
        offset -= moov_size
        if not free_size:
            # No free atoms and moov is correct, we are done!
            log.debug('mp4 already streamable -- copying')
            datastream.seek(skip)
            while True:
                block = datastream.read(CHUNK_SIZE)
                if not block:
                    break
                output(outfile, 0, block)
            return count

    # Read and fix moov
    datastream.seek(moov_pos)
    moov = StringIO(datastream.read(moov_size))

    # Ignore moov identifier and size, start reading children
    moov.seek(8)

    for atom_type in find_atoms(moov_size - 8, moov):
        # Read either 32-bit or 64-bit offsets
        ctype, csize = atom_type == "stco" and ("L", 4) or ("Q", 8)

        # Get number of entries
        version, entry_count = struct.unpack(">2L", moov.read(8))

        log.info("Patching %s with %d entries" % (atom_type, entry_count))

        # Read entries
        entries = struct.unpack(">" + ctype * entry_count,
                                moov.read(csize * entry_count))

        # Patch and write entries
        moov.seek(-csize * entry_count, os.SEEK_CUR)
        moov.write(struct.pack(">" + ctype * entry_count,
                               *[entry + offset for entry in entries]))

    log.info("Writing output...")

    # Write ftype
    for atom, pos, size in index:
        if atom == "ftyp":
            datastream.seek(pos)
            output(outfile, skip, datastream.read(size))

    # Write moov
    moov.seek(0)
    output(outfile, skip, moov.read())

    # Write the rest
    atoms = [item for item in index if item[0] not in ["ftyp", "moov", "free"]]
    for atom, pos, size in atoms:
        datastream.seek(pos)

        # Write in chunks to not use too much memory
        for x in range(size / CHUNK_SIZE):
            output(outfile, skip, datastream.read(CHUNK_SIZE))

        if size % CHUNK_SIZE:
            output(outfile, skip, datastream.read(size % CHUNK_SIZE))

    return count - skip
