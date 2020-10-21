#!/bin/python3
import os
import datetime
import subprocess
import re
import argparse
import logging
import sys
import traceback
import shutil
import time
from multiprocessing import Process

import psutil
import ruamel.yaml
import requests

from tasks.constants import JOBS_DIR, UUID_RE

"""
PRCI auto-cleaner which takes care of unused Vagrant boxes and libvirt inmages,
optionally we can clear also old job directories
"""

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
consoleHandler = logging.StreamHandler()
consoleHandler.setLevel(logging.DEBUG)
logger.addHandler(consoleHandler)

PRCI_CONFIG = '/root/.config/freeipa-pr-ci/config.yml'
PRCI_DEF_DIR = 'ipatests/prci_definitions'
LIBVIRT_IMAGES_DIR = '/var/lib/libvirt/images/'
LIBVIRT_IMAGE_BASE = ('freeipa-VAGRANTSLASH-{name}_vagrant_box_image'
                      '_{version}.img')
VAGRANT_NO_BOXES = 'There are no installed boxes!'

GH_RAW_PATH = 'https://raw.githubusercontent.com/{owner}/freeipa/{ref}/{path}'
GH_GRAPHQL_API = 'https://api.github.com/graphql'

CI_PREFIX_ID = 'freeipa/ci-'

TIMEOUT = 120
ACTIVE_CHECK_TIME = 350


def is_qemu_running():
    """
    Check if there is any qemu process running which indicates PRCI is active
    """
    all_procs = psutil.process_iter()
    return any([proc for proc in all_procs if proc.name().startswith('qemu')])


def start_prci():
    """
    Start PRCI systemd service
    """
    subprocess.run(['systemctl', 'start', 'prci'], timeout=TIMEOUT)


def stop_prci():
    """
    Stop PRCI systemd service
    """
    subprocess.run(['systemctl', 'stop', 'prci'], timeout=TIMEOUT)


def clear_journalctl():
    """
    Clear journalctl
    """
    subprocess.run(['journalctl', '--vacuum-time=2d'], timeout=TIMEOUT)


def status_prci():
    """
    Check PRCI systemd service status
    """
    res = subprocess.run(['systemctl', 'status', 'prci',
                          '--no-pager'], timeout=TIMEOUT)
    return not bool(res.returncode)


def load_yaml(yml_path):
    """
    Load yaml
    """
    try:
        with open(yml_path) as yml_file:
            return ruamel.yaml.safe_load(yml_file)
    except IOError as exc:
        logger.error('Failed to open %s: %s', yml_path, exc)
        sys.exit(1)
    except ruamel.yaml.YAMLError as exc:
        logger.error('Failed to parse YAML from %s: %s', yml_path, exc)
        sys.exit(1)


def get_old_job_dirs(max_days):
    """
    Get all PRCI job directories older than max_days if "--jobs_dir_exp"
    cmdline argument defined
    """
    old_job_dirs = []
    max_days = datetime.timedelta(max_days)
    for folder in os.scandir(JOBS_DIR):
        if folder.is_dir():
            mtime = datetime.datetime.fromtimestamp(
                os.path.getmtime(folder.path))
            if mtime - datetime.datetime.now() < max_days:
                old_job_dirs.append(folder.path)
    return old_job_dirs


def prune_exports_file(prune_dirs):
    """
    Vagrant entries in /etc/exports are not removed on vagrant destroy,
    hence /etc/exports must be accordingly cleaned-up before deleting
    PRCI job folders in order to avoid nfs-server issues.
    """
    entries_deleted = []
    try:
        if not os.geteuid()==0:
            print("\nUnable to prune /etc/exports. Must be run as root\n")
            return None
    except:
        pass

    exports = open('/etc/exports', 'r+')
    content = exports.readlines()
    exports.seek(0)
    for line in content:
        if "# VAGRANT-BEGIN" not in line:
            exports.write(line)
        else:
            next_item = content.index(line) + 1
            next_line = content[next_item]
            export_folder = next_line.partition(' ')[0].strip('"')
            if export_folder in prune_dirs:
                entries_deleted.append(export_folder)
                content.remove(line)
                content.remove(next_line)
            else:
                exports.write(line)

    # Write it out and close it.
    exports.truncate()
    exports.close()

    # sync exportfs before deleting the folders
    subprocess.run(['exportfs', '-ar'], timeout=TIMEOUT)

    return entries_deleted


def delete_job_dirs(old_dirs):
    """
    This function simply deletes a list of folders
    """
    dirs_deleted = []
    for folder in old_dirs:
        shutil.rmtree(folder)
        dirs_deleted.append(folder)
    return dirs_deleted


def del_dangling_libvirt_images():
    """
    Delete libivrt image leftovers after a VM was not cleaned completely
    """
    imgs_deleted = []
    for file in os.scandir(LIBVIRT_IMAGES_DIR):
        if re.match(UUID_RE+'.img', file.name):
            os.unlink(file.path)
            imgs_deleted.append(file.path)
    return imgs_deleted


def get_gh_token():
    """
    Get GH token from PRCI config file
    """
    return load_yaml(PRCI_CONFIG)['credentials']['token']


def list_vagrant_boxes():
    """
    List present Vagrant boxes which will be then deleted if not used
    on the branch it belongs to
    """
    res = subprocess.check_output(['vagrant', 'box', 'list'],
                                  timeout=TIMEOUT)
    if VAGRANT_NO_BOXES in res.decode():
        logger.info('No vagrant boxes found...')
        return []

    all_boxes = res.decode().strip().split('\n')
    return [x for x in all_boxes if x.startswith(CI_PREFIX_ID)]


class PRCIDef():
    def __init__(self, branch):
        self.branch = branch

    # owner of token is also our freeipa repo owner
    def prci_defs_query(self):
        """
        GraphQL query for getting all PRCI yaml job definition files
        """
        return {"query": """{
      viewer {
        repository(name: "freeipa") {
          object(expression: "%s:%s") {
          ... on Tree{
            entries{
              name
              type
              mode
            }
          }
        }
        }
      }
    }""" % (self.branch, PRCI_DEF_DIR)}

    def get_prci_def_files(self):
        """
        Get all PRCI yaml job definition files
        """
        res = requests.post(url=GH_GRAPHQL_API, json=self.prci_defs_query(),
                            headers={'Authorization': 'bearer {}'.format(
                                get_gh_token())})
        try:
            files = res.json()['data']['viewer']['repository']['object']['entries']
        except TypeError:
            logger.error(traceback.print_exc())
            logger.error('Could not get PRCI definition files from %s, please '
                         'check GraphQL query and result', PRCI_DEF_DIR)
            sys.exit(1)
        files = [os.path.join(PRCI_DEF_DIR, file['name']) for file in files]
        return files

    def get_templ_list(self, yaml_data):
        """
        Find list where template name and version are defined
        """
        if isinstance(yaml_data, list):
            for elem in yaml_data:
                res = self.get_templ_list(elem)
                if res is not None:
                    return res
        elif isinstance(yaml_data, dict):
            for key in yaml_data:
                val = yaml_data[key]
                if key == 'template':
                    if 'name' in val and 'version' in val:
                        return val
                res = self.get_templ_list(val)
                if res is not None:
                    return res
        return None

    def get_templ_data(self, yaml_data):
        """
        Get template name and version
        """
        templ_dict = self.get_templ_list(ruamel.yaml.safe_load(yaml_data))
        templ_name = templ_dict['name']
        templ_ver = templ_dict['version']
        return templ_name, templ_ver


class Box():

    def __init__(self, box):
        name, ver = box.split(' ', 1)
        self.box_templ_name = name
        self.box_templ_ver = ver.split()[-1][:-1]
        self.branch = name[name.find('-')+1:name.rfind('-')]

    def get_file_from_gh(self, path):
        repo_owner = load_yaml(PRCI_CONFIG)['repository']['owner']
        def_file_url = GH_RAW_PATH.format(owner=repo_owner,
                                          ref=self.branch,
                                          path=path)
        res = requests.get(def_file_url)
        if res.status_code != 200:
            logger.error('Failed to get %s', def_file_url)
            sys.exit(1)
        return res.text

    @property
    def is_box_used(self):
        """
        Check if Vagrant box is defined on the branch it belongs to
        """
        prci_def = PRCIDef(self.branch)

        # workaround for older 4-5 and 4-6 branches which are not using
        # "prci_definitions" folder
        if self.branch == 'ipa-4-5' or self.branch == 'ipa-4-6':
            def_files = ['.freeipa-pr-ci.yaml']
        else:
            def_files = prci_def.get_prci_def_files()

        for def_file in def_files:
            res = self.get_file_from_gh(def_file)
            if res.startswith(PRCI_DEF_DIR):
                # Fetch again if `def_file` is a symlink
                res = self.get_file_from_gh(res)
            templ_name, templ_ver = prci_def.get_templ_data(res)

            if (self.box_templ_name == templ_name and
                    self.box_templ_ver == templ_ver):
                logger.info('Box is used on %s in definition %s',
                            self.branch, def_file)
                return True

        return False

    def delete_box(self):
        """
        Delete Vagrant box
        """
        del_args = ['vagrant', 'box', 'remove', self.box_templ_name,
                    '--provider', 'libvirt', '--box-version',
                    self.box_templ_ver]

        subprocess.run(del_args, timeout=TIMEOUT)

    def delete_libvirt_img(self):
        """
        Delete libvirt image after its box was deleted
        """
        name = self.box_templ_name.split('/')[-1]
        del_args = ['virsh', 'vol-delete', '--pool', 'default',
                    LIBVIRT_IMAGE_BASE.format(
                        name=name, version=self.box_templ_ver)]

        subprocess.run(del_args, timeout=TIMEOUT)


def create_parser():
    """
    Create parser
    """
    parser = argparse.ArgumentParser(
        description='Perform auto-cleaning on runner')

    parser.add_argument(
        '--jobs_dir_exp', type=int, help='Number of days after which task job '
        'directories are deleted',
    )

    return parser


def run(args):
    """
    Run autocleaner
    """

    for vagrant_box in list_vagrant_boxes():
        logger.info('Checking if box %s is used', vagrant_box)
        box = Box(vagrant_box)
        if not box.is_box_used:
            logger.info('Deleting %s', vagrant_box)
            box.delete_box()
            box.delete_libvirt_img()

    if args.jobs_dir_exp:
        # search old prci job dirs to be deleted
        old_dirs = get_old_job_dirs(args.jobs_dir_exp)
        if not old_dirs:
            logger.info('No job dir qualified for erase')
        else:
            # prune and re-sync exportfs to avoid nfs-server issues
            prune_exports = prune_exports_file(old_dirs)
            if prune_exports:
                logger.info('Following /etc/exports entries deleted: ')
                logger.info(prune_exports)
            # delete old prci job dirs
            dirs_deleted = delete_job_dirs(old_dirs)
            if dirs_deleted:
                logger.info('Following directories deleted: ')
                logger.info(dirs_deleted)

    res = del_dangling_libvirt_images()
    if not res:
        logger.info('No dangling libvirt images found...')
    else:
        logger.info('Following dangling libvirt images deleted: ')
        logger.info(res)


def main():
    """
    Main
    """
    parser = create_parser()
    args = parser.parse_args()

    try:
        while True:
            if not is_qemu_running():
                logger.info('PRCI not active, stopping systemd service...')
                stop_prci()
                logger.info('Clearing journalctl, retain the past two days...')
                clear_journalctl()
                logger.info('PRCI service stopped...')
                logger.info('Started auto-cleaning process...')
                cleaning_process = Process(target=run, args=(args,))
                cleaning_process.start()
                cleaning_process.join(timeout=TIMEOUT)
                break
            else:
                logger.info('PRCI active, checking again in 5 minutes...')
                time.sleep(ACTIVE_CHECK_TIME)
                continue
    finally:
        # lets ensure PRCI is always started when we quit
        start_prci()
        if status_prci():
            logger.info('Job finished, PRCI service started again...')
        else:
            logger.error('Failed to start PRCI after job finished !!!')
            # FIXME: implement alarm mail


if __name__ == '__main__':
    main()
    
  
