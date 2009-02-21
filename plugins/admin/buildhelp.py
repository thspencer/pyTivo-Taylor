import os

SCRIPTDIR = os.path.dirname(__file__)

## Build initial help list
help_list = {}
title = ''
settings_known = {}
multiline = ''
f = open(os.path.join(SCRIPTDIR, 'help.txt'))
try:
    for line in f:
        line = line.strip()
        if multiline:
            if line.endswith('+\\'):
                multiline += line[:-2]
            else:
                multiline += line
                help_list[title].append(multiline)
                multiline = ''
            continue
        if not line or line.startswith('#'):
            # skip blank or commented lines
            continue
        if ':' not in line:
            title = line
            help_list[title] = []
        else:
            value, data = [x.strip() for x in line.split(':', 1)]
            if value.lower() == 'available in':
                # special setting to create section_known array
                for section in data.split(','):
                    section = section.lower().strip()
                    if section not in settings_known:
                        settings_known[section] = []
                    settings_known[section].append(title)
            else:
                if line.endswith('+\\'):
                    multiline += line[:-2]
                else:
                    help_list[title].append(line)
finally:
    f.close()
## Done building help list

def gethelp():
    return help_list

def getknown(section):
    return settings_known[section]
