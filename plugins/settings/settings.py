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
            handler.send_fixed(GOODBYE_MSG, 'text/plain')
            if handler.server.in_service:
                handler.server.stop = True
            else:
                handler.server.shutdown()
            handler.server.socket.close()
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
            handler.server.socket.close()
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

        t = Template(SETTINGS_TEMPLATE, filter=EncodeUnicode)
        t.container = handler.cname
        t.quote = quote
        t.server_data = dict(config.config.items('Server', raw=True))
        t.server_known = buildhelp.getknown('server')
        t.hd_tivos_data = dict(config.config.items('_tivo_HD', raw=True))
        t.hd_tivos_known = buildhelp.getknown('hd_tivos')
        t.sd_tivos_data = dict(config.config.items('_tivo_SD', raw=True))
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
        handler.send_html(str(t))

    def UpdateSettings(self, handler, query):
        config.reset()
        for section in ['Server', '_tivo_SD', '_tivo_HD']:
            new_setting = new_value = ' '
            for key, value in query.items():
                key = key.replace('opts.', '', 1)
                if key.startswith(section + '.'):
                    _, option = key.split('.')
                    value = value[0]
                    if not config.config.has_section(section):
                        config.config.add_section(section)
                    if option == 'new__setting':
                        new_setting = value
                    elif option == 'new__value':
                        new_value = value
                    elif value == ' ':
                        config.config.remove_option(section, option)
                    else:
                        config.config.set(section, option, value)
            if not(new_setting == ' ' and new_value == ' '):
                config.config.set(section, new_setting, new_value)

        sections = query['Section_Map'][0].split(']')[:-1]
        for section in sections:
            ID, name = section.split('|')
            if query[ID][0] == 'Delete_Me':
                config.config.remove_section(name)
                continue
            if query[ID][0] != name:
                config.config.remove_section(name)
                config.config.add_section(query[ID][0])
            for key, value in query.items():
                key = key.replace('opts.', '', 1)
                if key.startswith(ID + '.'):
                    _, option = key.split('.')
                    value = value[0]
                    if option == 'new__setting':
                        new_setting = value
                    elif option == 'new__value':
                        new_value = value
                    elif value == ' ':
                        config.config.remove_option(query[ID][0], option)
                    else:
                        config.config.set(query[ID][0], option, value)
            if not(new_setting == ' ' and new_value == ' '):
                config.config.set(query[ID][0], new_setting, new_value)
        if query['new_Section'][0] != ' ':
            config.config.add_section(query['new_Section'][0])
        config.write()

        handler.redir(SETTINGS_MSG, 5)
    
    def Update(self, handler, query):
        import update

        try: # should always be a list: (BOOL, STRING)
            result = update.update_request(config.getForceUpdate())
        except: # catch-all for exceptions, prints last traceback
            import sys, traceback
            update_msg = """<h3>Update Failed</h3> <p>Message:<ul>
                          <li>Update process failed for unknown reasons.
                          See debug log for possible cause.
                          </li></ul></p>"""
            handler.redir(update_msg, 20)
            traceback.print_exc()
            sys.exc_clear()
            return

        # update has failed with reasons
        if not result[0]:
            update_msg = ("""<h3>Update Failed</h3><p>Message:<ul>
                          <li>%s   See debug log for additional details.
                          </li></ul></p>""" % result[1])
            handler.redir(update_msg, 20)
            return

        # update was successful
        ### auto restart code not finished so require user to manual restart
        update_msg = """<h3>Update Successful</h3><p>Message:<ul>
                     <li>A manual restart of pyTivo is required 
                     to complete the update process.</li></ul></p>"""

        handler.redir(update_msg, 20)
