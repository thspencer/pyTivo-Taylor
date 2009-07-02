import os

SCRIPTDIR = os.path.dirname(__file__)

## Build initial help list
help_list = {}
title = ''
settings_known = {}
titlemode = True
f = open(os.path.join(SCRIPTDIR, 'help.txt'))
try:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#'):
            # skip blank or commented lines
            titlemode = True
        elif line.startswith('>'):
            help_list[title][-1] += ' ' + line[1:]
        elif ':' not in line:
            if titlemode:
                title = line
                help_list[title] = []
                titlemode = False
            else:
                help_list[title][-1] += ' ' + line
        else:
            titlemode = False
            value, data = [x.strip() for x in line.split(':', 1)]
            if value.lower() == 'available in':
                # special setting to create section_known array
                for section in data.split(','):
                    section = section.lower().strip()
                    if section not in settings_known:
                        settings_known[section] = []
                    settings_known[section].append(title)
            else:
                help_list[title].append(line)
finally:
    f.close()
## Done building help list

def gethelp():
    return help_list

def getknown(section):
    return settings_known[section]
