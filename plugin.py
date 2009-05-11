import os
import random
import shutil
import sys
import threading
import urllib

from Cheetah.Filters import Filter

if os.path.sep == '/':
    quote = urllib.quote
    unquote = urllib.unquote_plus
else:
    quote = lambda x: urllib.quote(x.replace(os.path.sep, '/'))
    unquote = lambda x: os.path.normpath(urllib.unquote_plus(x))

class Error:
    CONTENT_TYPE = 'text/html'

def GetPlugin(name):
    try:
        module_name = '.'.join(['plugins', name, name])
        module = __import__(module_name, globals(), locals(), name)
        plugin = getattr(module, module.CLASS_NAME)()
        return plugin
    except ImportError:
        print 'Error no', name, 'plugin exists. Check the type ' \
        'setting for your share.'
        return Error

class EncodeUnicode(Filter):
    def filter(self, val, **kw):
        """Encode Unicode strings, by default in UTF-8"""

        encoding = kw.get('encoding', 'utf8')

        if type(val) == str:
            try:
                val = val.decode('utf8')
            except:
                if sys.platform == 'darwin':
                    val = val.decode('macroman')
                else:
                    val = val.decode('iso8859-1')
        elif type(val) != unicode:
            val = str(val)
        return val.encode(encoding)

class Plugin(object):

    random_lock = threading.Lock()

    CONTENT_TYPE = ''

    def __new__(cls, *args, **kwds):
        it = cls.__dict__.get('__it__')
        if it is not None:
            return it
        cls.__it__ = it = object.__new__(cls)
        it.init(*args, **kwds)
        return it

    def init(self):
        pass

    def send_file(self, handler, path, query):
        handler.send_response(200)
        handler.end_headers()
        f = open(path, 'rb')
        shutil.copyfileobj(f, handler.wfile)
        f.close()

    def get_local_base_path(self, handler, query):

        subcname = query['Container'][0]
        container = handler.server.containers[subcname.split('/')[0]]

        return os.path.normpath(container['path'])

    def get_local_path(self, handler, query):

        subcname = query['Container'][0]
        container = handler.server.containers[subcname.split('/')[0]]

        path = os.path.normpath(container['path'])
        for folder in subcname.split('/')[1:]:
            if folder == '..':
                return False
            path = os.path.join(path, folder)
        return path

    def item_count(self, handler, query, cname, files, last_start=0):
        """Return only the desired portion of the list, as specified by 
           ItemCount, AnchorItem and AnchorOffset. 'files' is either a 
           list of strings, OR a list of objects with a 'name' attribute.
        """
        def no_anchor(handler, anchor):
            handler.server.logger.warning('Anchor not found: ' + anchor)

        totalFiles = len(files)
        index = 0

        if totalFiles and 'ItemCount' in query:
            count = int(query['ItemCount'][0])

            if 'AnchorItem' in query:
                bs = '/TiVoConnect?Command=QueryContainer&Container='
                local_base_path = self.get_local_base_path(handler, query)

                anchor = query['AnchorItem'][0]
                if anchor.startswith(bs):
                    anchor = anchor.replace(bs, '/', 1)
                anchor = unquote(anchor)
                anchor = anchor.replace(os.path.sep + cname, local_base_path, 1)
                if not '://' in anchor:
                    anchor = os.path.normpath(anchor)

                if type(files[0]) == str:
                    filenames = files
                else:
                    filenames = [x.name for x in files]
                try:
                    index = filenames.index(anchor, last_start)
                except ValueError:
                    if last_start:
                        try:
                            index = filenames.index(anchor, 0, last_start)
                        except ValueError:
                            no_anchor(handler, anchor)
                    else:
                        no_anchor(handler, anchor) # just use index = 0

                if count > 0:
                    index += 1

                if 'AnchorOffset' in query:
                    index += int(query['AnchorOffset'][0])

                #foward count
                if count >= 0:
                    files = files[index:index + count]
                #backwards count
                else:
                    if index + count < 0:
                        count = -index
                    files = files[index + count:index]
                    index += count

            else:  # No AnchorItem

                if count >= 0:
                    files = files[:count]
                else:
                    index = count % len(files)
                    files = files[count:]

        return files, totalFiles, index

    def get_files(self, handler, query, filterFunction=None, force_alpha=False):

        def build_recursive_list(path, recurse=True):
            files = []
            try:
                for f in os.listdir(path):
                    if f.startswith('.'):
                        continue
                    f = os.path.join(path, f)
                    if recurse and os.path.isdir(f):
                        files.extend(build_recursive_list(f))
                    else:
                       if not filterFunction or filterFunction(f, file_type):
                           files.append(f)
            except:
                pass
            return files

        subcname = query['Container'][0]
        cname = subcname.split('/')[0]
        path = self.get_local_path(handler, query)

        file_type = query.get('Filter', [''])[0]

        recurse = query.get('Recurse', ['No'])[0] == 'Yes'
        files = build_recursive_list(path, recurse)

        totalFiles = len(files)

        def dir_sort(x, y):
            xdir = os.path.isdir(os.path.join(path, x))
            ydir = os.path.isdir(os.path.join(path, y))

            if xdir == ydir:
                return name_sort(x, y)
            else:
                return ydir - xdir

        def name_sort(x, y):
            return cmp(x, y)

        def date_sort(x, y):
            return cmp(os.stat(y).st_mtime, os.stat(x).st_mtime)

        sortby = query.get('SortOrder', ['Normal'])[0]
        if sortby == 'Random':
            seed = query.get('RandomSeed', ['1'])[0]
            self.random_lock.acquire()
            random.seed(seed)
            random.shuffle(files)
            self.random_lock.release()
        elif force_alpha:
            files.sort(dir_sort)
        elif sortby == '!CaptureDate':
            files.sort(date_sort)
        else:
            files.sort(name_sort)

        # Trim the list
        return self.item_count(handler, query, cname, files)
