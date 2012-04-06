import os
import logging
import tarfile
import urllib2
from pygithub import github # obtained from https://github.com/dustin/py-github

import config

logger = logging.getLogger('pyTivo.update')

# uses github api, customize for desired fork
GIT_MEMBER  = 'thspencer'
GIT_PROJECT = 'pyTivo-Taylor' 
GIT_BRANCH  = 'master'
PACKAGE_URL = ('https://github.com/%s/%s/tarball/%s/' %
               (GIT_MEMBER, GIT_PROJECT, GIT_BRANCH))

# returns 'result'(bool, string) to video.settings.settings.py
def update_request():
    pyTivo_dir = os.path.dirname(__file__)
    version_file = os.path.join(pyTivo_dir, 'version.txt')

    # determine if previous install was git or manual
    type = install_type(pyTivo_dir)
    result = (True, '')

    while True:        
        # determine installed commit version from local git or version.txt
        cur_hash = find_current_version(pyTivo_dir, version_file, type)

        if not cur_hash:
            message = 'Installed version could not be determined.'
            logger.error(message)
            result = (False, '%s' % message)
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
            if type == 'git': # UPDATE WHEN GIT SUPPORT ADDED
                message = 'Git installs are not currently supported.'
                logger.error(message)
                result = (False, '%s' % message)
                break
                #update = do_update_git(pyTivo_dir, newest_hash)
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

# search version file for current commit hash
def find_current_version(pyTivo_dir, version_file, type):
    if type == 'git':
        logger.error('** Git installs are not currently supported.')
        return None
    else:
        version_file = os.path.join(pyTivo_dir, 'version.txt')

        try:
            f = open(version_file, 'rt')
            cur_hash = f.read().strip('\r\n') # strip out unwanted chars
            f.close()
        except IOError:
            logger.error('Version file not found')
            return None

        if not cur_hash:
            logger.error('Version file was empty')
            return None

    logger.info('Current version is %s' % cur_hash[:7])
    logger.debug('Current commit - long hash: %s' % cur_hash)
    return cur_hash	

# uses github api to find latest commit hash
def find_newest_commit(cur_hash):
    newest_commit = None
    g = github.GitHub()

    try:
        for ghCommit in g.commits.forBranch(GIT_MEMBER, GIT_PROJECT, GIT_BRANCH):
            if not newest_commit:
                newest_commit = ghCommit.id
                if not cur_hash:
                    logger.debug('Current commit hash not found.')
                    break
            if ghCommit.id == cur_hash:
                break
    except (urllib2.HTTPError, urllib2.URLError), e:
        logger.error('pyTivo repository not found. Network may be down.\n%s' % e)
        return False

    logger.info('Latest commit found is: %s'
                % newest_commit[:7])
    return newest_commit

def do_update_git(pyTivo_dir, latest):
    logger.error('** Git update not implemented yet')
    return None

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