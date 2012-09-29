import config
import logging
import os
import subprocess
import sys
import tarfile
import urllib2

logger = logging.getLogger('pyTivo.update')

# uses GitHub API v3, customize for desired fork
GIT_MEMBER  = 'thspencer'
GIT_PROJECT = 'pyTivo-Taylor' 
GIT_BRANCH  = 'master'
PACKAGE_URL = ('https://github.com/%s/%s/tarball/%s/' %
               (GIT_MEMBER, GIT_PROJECT, GIT_BRANCH))

# GitHub API v3
class GitHub(object):
    def _access_API(self, path, params=None):
        # json requires Python 2.6 or higher
        # can use simplejson if additional compatibility is required
        import json

        url = 'https://api.github.com/' + '/'.join(path)

        if params and type(params) is dict:
            url += '?' + '&'.join([str(x) + '=' + str(params[x]) for x in params.keys()])

        return json.load(urllib2.urlopen(url))

    def commits(self, member, project, branch='master'):
        return self._access_API(['repos', member, project, 'commits'], {'sha': branch})

# returns 'result'(bool, string) to video.settings.settings.py
def update_request(forced):

    # tarfile.extractall() requires Python 2.5 or higher
    # json requires Python 2.6 or higher
    if sys.version_info[0] != 2 or sys.version_info[1] < 6:
        message = 'ERROR: pyTivo updater requires Python 2.6 or any higher 2.x version.'
        logger.error(message)
        result = (False, '%s' % message)
        return result

    if sys.platform == 'win32':
        encoding = 'iso8859-1'
    else:
        encoding = 'utf-8'

    pyTivo_dir = unicode(os.path.dirname(__file__), encoding)
    version_file = os.path.join(pyTivo_dir, 'version.txt')

    # determine if previous install was git or manual
    type = install_type(pyTivo_dir)
    result = (True, '')

    while True:        
        # determine installed commit version from local git or version.txt
        cur_hash = find_current_version(pyTivo_dir, version_file, type, forced)

        if not cur_hash:
            message = 'Installed version could not be determined.'
            logger.error(message)
            if type == 'git':
                result = (False, '%s' % message)
            else:
                result = (False, """%s<li>The update can be forced by setting
                                    'force_update' to True in the Server 
                                    settings.</li>""" % message)
            break

        # determine lastest available commit from pyTivo repository
        newest_hash = find_newest_commit(cur_hash)

        if not newest_hash:
            message = 'Could not determine latest pyTivo commit.'
            logger.error(message)
            result = (False, '%s' % message)
            break

        # determine if update is really needed
        if cur_hash == newest_hash:
            message = 'Update not needed.  Installed version is latest.'
            logger.error(message)
            result = (False, '%s' % message)
            break
        # proceed with update
        else:
            if type == 'git':
                update = do_update_git(pyTivo_dir, newest_hash)
            else:
                update = do_update_manual(pyTivo_dir, version_file, newest_hash)
            if update == 'no_permission':
                message = ('Unable able to update due to permissions error.')
                logger.error(message)
                result = (False, '%s' % message)
                break
            elif not update:
                message = 'Update was not successful.'
                logger.error(message)
                result = (False, '%s' % message)
                break
            logger.info('Update was successful!')
        break

    return result

# find and return install type: manual, git, None
def install_type(pyTivo_dir):        
    git_dir = os.path.join(pyTivo_dir, '.git')

    if os.path.isdir(git_dir):
        type = 'git'
    else:
        type = 'manual'

    logger.debug('Type of install detected is: %s' % type)
    return type

# search for current commit hash
def find_current_version(pyTivo_dir, version_file, type, forced):
    cur_hash = None

    if type == 'git':
        git_dir = os.path.join(pyTivo_dir, '.git')
        head_file = os.path.join(git_dir, 'HEAD')

        if os.path.isfile(head_file):
            f = open(head_file, 'rt')
            try: # should not contain unicode chars but test just in case
                git_ref = f.read().decode('utf-8')
            except:
                if sys.platform == 'darwin':
                    git_ref = f.read().decode('macroman')
                else:
                    git_ref = f.read().decode('iso8859-1')
            f.close()
        else:
            logger.error('Git HEAD file not located')
            return cur_hash

        git_ref = git_ref.split()
        if len(git_ref) > 1 and git_ref[1].startswith('refs'):
            git_ver_file = os.path.join(git_dir, git_ref[1])
            if os.path.isfile(git_ver_file):
                f = open(git_ver_file, 'rt')
                try: # should not contain unicode chars but test just in case
                    cur_hash = f.read().decode('utf-8')
                except:
                    if sys.platform == 'darwin':
                        cur_hash = f.read().decode('macroman')
                    else:
                        cur_hash = f.read().decode('iso8859-1')
                f.close()

        if not cur_hash:
            logger.error('Current commit not found; local repository may be corrupt')
    else:
        if os.path.isfile(version_file):
            f = open(version_file, 'rt')
            try: # should not contain unicode chars but test just in case
                cur_hash = f.read().decode('utf-8')
            except:
                if sys.platform == 'darwin':
                    cur_hash = f.read().decode('macroman')
                else:
                    cur_hash = f.read().decode('iso8859-1')
            f.close()
        else:
            logger.error('Version file not found')
            if forced: # if force_update in conf file is True then update
                cur_hash = 'unknown'
                logger.info('Forcing update')
            else:
                return cur_hash

        if not cur_hash:
            logger.error('Version file was empty or corrupt')
            if forced: # if force_update in conf file is True then update
                cur_hash = 'unknown'
                logger.info('Forcing update')
    if cur_hash:
        # strip out unwanted chars
        cur_hash = cur_hash.strip('\r\n ')
        logger.info('Current version is: %s' % cur_hash[:7])
        logger.debug('Current commit - long hash: %s' % cur_hash)

    return cur_hash	

# uses GitHub API v3 to find latest commit hash
def find_newest_commit(cur_hash):
    newest_commit = None
    g = GitHub()

    try:
        for ghCommit in g.commits(GIT_MEMBER, GIT_PROJECT, GIT_BRANCH):
            if not newest_commit:
                newest_commit = ghCommit['sha']
                if not cur_hash:
                    logger.debug('Current commit hash not found.')
                    break
            if ghCommit['sha'] == cur_hash:
                break
    except (urllib2.HTTPError, urllib2.URLError), e:
        logger.error('pyTivo repository not found. Network may be down.\n%s' % e)
        return False

    if not newest_commit:
        logger.error('Latest commit not found. Verify GitHub identity.')
    else:
    	logger.info('Latest commit found is: %s' % newest_commit[:7])
    return newest_commit

# use system Git executable to pull latest pyTivo commit
# version info will be updated by Git
def do_update_git(pyTivo_dir, latest):
    git_path = config.get_bin('git')
    output, err = None, None

    logger.debug('Git executable path is: %s' % git_path)

    if git_path:
        try:
            # this may not be syncing with GitHub but another remote
            # it depends on the local git repository configuration
            exec_git = subprocess.Popen([git_path, 'pull origin', GIT_BRANCH],
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        cwd=pyTivo_dir)
            output, err = exec_git.communicate()
            if 'not a git command' in output: # try alternate method if pull origin fails
                exec_git = subprocess.Popen([git_path, 'pull'], stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, cwd=pyTivo_dir)
                output, err = exec_git.communicate()
            logger.debug('Git output:\n%s' % output)
            if err:
                logger.debug('Git error output: %s' % err)
        except OSError, e:
            logger.error('There was an error during Git execution: %s' % e)
            return False

        if not output or err:
            logger.error('Git produced no output')
            return False

        # catch fatal error from Git
        # reason is usually cwd is not a proper git install or is corrupt
        if 'fatal:' in output or err:
            logger.error('Install corrupt or not a git repository:\n%s' % pyTivo_dir)
            return False

        if 'error:' in output or err:
            logger.error('Unable to update existing files')
            return 'no_permission'

        # catch already up-to-date git status
        # if user sees this there may be a bug in the current version detection
        # or are using an out of date remote repository that is out of sync with GitHub.
        if 'Already up-to-date' in output:
            logger.error('Version mismatch. Local git may be fetching ' +
                         'from an outdated remote repository.')
            logger.info('Recommended to use GitHub repository instead from:\n%s' %
                         PACKAGE_URL.split('tarball')[0])
            return False

        # check for successful output at end of git pull.
        # typically will be indication of files changed, insertions, or deletions
        if ('changed' and 'insertions' and 'deletions') in output:
            return True
        else:
            logger.error('Can not determine if Git pull was successful; assuming failure')
            return False
    else:
        logger.error('Git executable not found; set git path in pyTivo.conf')

    return False

# update manual install type
def do_update_manual(pyTivo_dir, version_file, latest):
    download_url = PACKAGE_URL + latest	
    update_dir = os.path.join(pyTivo_dir, 'update')

    # create update directory if does not exist
    if not os.path.exists(update_dir):
        logger.debug('Creating update directory.')
        try:
            os.mkdir(update_dir)
        except OSError, (errno, errstr):
            logger.error('Unable to create update directory. %s' % errstr)
            if errno == 13:
                return 'no_permission'
            else:
                return False

    logger.debug('Retrieving latest update: %s' % download_url)
    try:
        package = urllib2.urlopen(download_url)
    except (urllib2.HTTPError, urllib2.URLError), e:
        logger.error('Download of pyTivo package failed\n%s' % e)
        return False

    # package name is commit short hash
    package_name = ('pyTivo-%s' % latest[:7])
    package_path = os.path.join(update_dir, package_name)

    # write file to disk:
    try:
        f = open(package_path, 'wb')
        f.write(package.read())
        f.close()
    except IOError, e:
        logger.error('Could not write to disk.\n%s' % e)
        return False
    except OSError, (errno, errstr):
        logger.error('Could not write to disk. %s' % errstr)
        if errno == 13:
            return 'no_permission'
        else:
            return False

    # extract data to update directory
    try:
        data = tarfile.open(package_path)
        data.extractall(update_dir)
        data.close()
        logger.debug('Extracting package: %s' % package_path)
    except IOError, e:
        logger.error('Could not write to disk.\n%s' % e)
        return False
    except OSError, (errno, errstr):
        logger.error('Could not write to disk. %s' % errstr)
        if errno == 13:
            return 'no_permission'
        else:
            return False

    # remove downloaded package
    logger.debug('Deleting package: %s' % package_path)
    try:
        os.remove(package_path)
    except OSError, (errno, errstr):
        logger.error('Unable to remove update package. %s' % errstr)
        if errno == 13:
            return 'no_permission'
        else:
            return False

    # find extracted folder
    package_dir = []
    for x in os.listdir(update_dir):
        path = os.path.join(update_dir, x)
        if os.path.isdir(path):
            package_dir.append(path)

    # only the extracted directory should exist here
    if len(package_dir) != 1:
    	logger.error('Update data is invalid: %s' % package_dir)
        logger.error('Make certain update directory is empty.')        
        return False

    # get name of extracted folder
    update_name = os.path.join(update_dir, package_dir[0])

    # walk extracted folder and process new files
    for root, dirs, files in os.walk(update_name): # dirs var unused
        root = root[len(update_name) + 1:]
        try:
            for filename in files:
                old_path = os.path.join(update_name, root, filename)
                new_path = os.path.join(pyTivo_dir, root, filename)

                # remove update files after being processed
                if os.path.isfile(new_path):
                    try:
                        os.remove(new_path)
                    except OSError:
                        # don't fail update if unable to remove update files
                        logger.error('Unable to remove file: %s' % new_path)

                os.renames(old_path, new_path)

        except OSError, (errno, errstr):
            logger.error('Unable to update existing files. %s' % errstr)
            if errno == 13:
                return 'no_permission'
            else:
                return False

    # add commit hash of downloaded package to version.txt
    logger.debug('Updating current commit hash in version file.')
    try:
        f = open(version_file, 'w')
        f.write(latest)
        f.close()
    except IOError, e:
    	logger.error('Unable to update version file.\n%s' % e)
        return False
    except OSError, (errno, errstr):
        logger.error('Unable to update version file. %s' % errstr)
        if errno == 13:
            return 'no_permission'
        else:
            return False

    return True
