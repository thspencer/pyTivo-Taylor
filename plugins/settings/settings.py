import logging
import os
from urllib import quote

from Cheetah.Template import Template

import buildhelp
import config
from plugin import EncodeUnicode, Plugin

SCRIPTDIR = os.path.dirname(__file__)

CLASS_NAME = 'Settings'

# Some error/status message templates

RESET_MSG = """<h3>Soft Reset</h3> <p>pyTivo has reloaded the 
pyTivo.conf file and all changes should now be in effect.</p>"""

RESTART_MSG = """<h3>Restart</h3> <p>pyTivo will now restart.</p>"""

GOODBYE_MSG = 'Goodbye.\n'

SETTINGS_MSG = """<h3>Settings Saved</h3> <p>Your settings have been 
saved to the pyTivo.conf file. However you may need to do a <b>Soft 
Reset</b> or <b>Restart</b> before these changes will take effect.</p>"""

# Preload the templates
tsname = os.path.join(SCRIPTDIR, 'templates', 'settings.tmpl')
SETTINGS_TEMPLATE = file(tsname, 'rb').read()

class Settings(Plugin):
    CONTENT_TYPE = 'text/html'

    def Quit(self, handler, query):
        if hasattr(handler.server, 'shutdown'):
            handler.send_response(200)
            handler.send_header('Content-Type', 'text/plain')
            handler.send_header('Content-Length', len(GOODBYE_MSG))
            handler.send_header('Connection', 'close')
            handler.end_headers()
            handler.wfile.write(GOODBYE_MSG)
            if handler.server.in_service:
                handler.server.stop = True
            else:
                handler.server.shutdown()
        else:
            handler.send_error(501)

    def Restart(self, handler, query):
        if hasattr(handler.server, 'shutdown'):
            handler.redir(RESTART_MSG, 10)
            handler.server.restart = True
            if handler.server.in_service:
                handler.server.stop = True
            else:
                handler.server.shutdown()
        else:
            handler.send_error(501)

    def Reset(self, handler, query):
        config.reset()
        handler.server.reset()
        handler.redir(RESET_MSG, 3)
        logging.getLogger('pyTivo.settings').info('pyTivo has been soft reset.')

    def Settings(self, handler, query):
        # Read config file new each time in case there was any outside edits
        config.reset()

        shares_data = []
        for section in config.config.sections():
            if not (section.startswith('_tivo_')
                    or section.startswith('Server')):
                if (not (config.config.has_option(section, 'type')) or
                    config.config.get(section, 'type').lower() not in
                    ['settings', 'togo']):
                    shares_data.append((section,
                                        dict(config.config.items(section,
                                                                 raw=True))))

        cname = query['Container'][0].split('/')[0]
        t = Template(SETTINGS_TEMPLATE, filter=EncodeUnicode)
        t.container = cname
        t.quote = quote
        t.server_data = dict(config.config.items('Server', raw=True))
        t.server_known = buildhelp.getknown('server')
        if config.config.has_section('_tivo_HD'):
            t.hd_tivos_data = dict(config.config.items('_tivo_HD', raw=True))
        else:
            t.hd_tivos_data = {}
        t.hd_tivos_known = buildhelp.getknown('hd_tivos')
        if config.config.has_section('_tivo_SD'):
            t.sd_tivos_data = dict(config.config.items('_tivo_SD', raw=True))
        else:
            t.sd_tivos_data = {}
        t.sd_tivos_known = buildhelp.getknown('sd_tivos')
        t.shares_data = shares_data
        t.shares_known = buildhelp.getknown('shares')
        t.tivos_data = [(section, dict(config.config.items(section, raw=True)))
                        for section in config.config.sections()
                        if section.startswith('_tivo_')
                        and not section.startswith('_tivo_SD')
                        and not section.startswith('_tivo_HD')]
        t.tivos_known = buildhelp.getknown('tivos')
        t.help_list = buildhelp.gethelp()
        t.has_shutdown = hasattr(handler.server, 'shutdown')
        handler.send_response(200)
        handler.send_header('Content-Type', 'text/html; charset=utf-8')
        handler.send_header('Expires', '0')
        handler.end_headers()
        handler.wfile.write(t)

    def UpdateSettings(self, handler, query):
        config.reset()
        for section in ['Server', '_tivo_SD', '_tivo_HD']:
            new_setting = new_value = ' '
            for key in query:
                if key.startswith('opts.'):
                    data = query[key]
                    del query[key]
                    key = key[5:]
                    query[key] = data
                if key.startswith(section + '.'):
                    _, option = key.split('.')
                    if not config.config.has_section(section):
                        config.config.add_section(section)
                    if option == 'new__setting':
                        new_setting = query[key][0]
                    elif option == 'new__value':
                        new_value = query[key][0]
                    elif query[key][0] == ' ':
                        config.config.remove_option(section, option)
                    else:
                        config.config.set(section, option, query[key][0])
            if not(new_setting == ' ' and new_value == ' '):
                config.config.set(section, new_setting, new_value)

        sections = query['Section_Map'][0].split(']')
        sections.pop() # last item is junk
        for section in sections:
            ID, name = section.split('|')
            if query[ID][0] == 'Delete_Me':
                config.config.remove_section(name)
                continue
            if query[ID][0] != name:
                config.config.remove_section(name)
                config.config.add_section(query[ID][0])
            for key in query:
                if key.startswith(ID + '.'):
                    _, option = key.split('.')
                    if option == 'new__setting':
                        new_setting = query[key][0]
                    elif option == 'new__value':
                        new_value = query[key][0]
                    elif query[key][0] == ' ':
                        config.config.remove_option(query[ID][0], option)
                    else:
                        config.config.set(query[ID][0], option, query[key][0])
            if not(new_setting == ' ' and new_value == ' '):
                config.config.set(query[ID][0], new_setting, new_value)
        if query['new_Section'][0] != ' ':
            config.config.add_section(query['new_Section'][0])
        config.write()

        handler.redir(SETTINGS_MSG, 5)
