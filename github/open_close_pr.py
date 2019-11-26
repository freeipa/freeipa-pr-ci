#!/usr/bin/python3

import os
import shutil
import github3
import argparse
import logging
import ruamel.yaml
from cachecontrol.adapter import CacheControlAdapter
import git
from git import Repo
from urllib.parse import urljoin
import subprocess
import requests


REF_FORMAT = 'refs/heads/'
DEFAULT_COMMIT_MSG = 'automated commit'
FREEIPA_PRCI_CONFIG_FILE = '.freeipa-pr-ci.yaml'
PRCI_DEF_DIR = 'ipatests/prci_definitions'
REMOTE_REPO = 'https://github.com/freeipa/freeipa.git'
UPSTREAM_REMOTE_REF = 'upstream'
MYGITHUB_REMOTE_REF = 'mygithub'
TEMPL_NAME = '{flow}-{branch}-f{fedora_version}'
VAGRANT_LINK = 'https://app.vagrantup.com/api/v1/box/freeipa/'


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
consoleHandler = logging.StreamHandler()
consoleHandler.setLevel(logging.DEBUG)
logger.addHandler(consoleHandler)


def load_yaml(yml_path):
    yaml = ruamel.yaml.YAML()
    try:
        with open(yml_path, 'r+') as yml_file:
            return yaml.safe_load(yml_file)
    except IOError as exc:
        raise argparse.ArgumentTypeError(
            'Failed to open {}: {}'.format(yml_path, exc))
    except yaml.YAMLError as exc:
        raise argparse.ArgumentTypeError(
            'Failed to parse YAML from {}: {}'.format(yml_path, exc))


def dump_yaml(yml_path, yml_data):
    yaml = ruamel.yaml.YAML()
    try:
        with open(yml_path, 'w') as yml_file:
            yaml.dump(yml_data, yml_file)
    except OSError:
        logger.error('Cannot write to %s', yml_path)
        raise


class AutomatedPR(object):

    def __init__(self, github_token, repo, args):
        github = github3.login(token=github_token)
        github.session.mount('https://api.github.com', CacheControlAdapter())
        self.repo = github.repository(repo['owner'], repo['name'])
        self.upstream_repo = github.repository('freeipa', 'freeipa')
        self.args = args

    def get_newest_templ_ver(self):
        atlas_conf = load_yaml(self.args.atlas_config)
        token = atlas_conf['token']
        bearer = 'Bearer {}'.format(token)

        templ_name = TEMPL_NAME.format(
            flow=self.args.flow,
            branch=self.args.branch,
            fedora_version=self.args.fedora_ver
        )

        url = urljoin(VAGRANT_LINK, templ_name)

        headers = {'Content-Type': 'application/json',
                   'Authorization': bearer}

        res = requests.get(url, headers=headers)
        res.raise_for_status()

        latest_ver = res.json()['current_version']['version']
        logger.info('Latest %s Vagrant box version is: %s',
                    self.args.branch,
                    latest_ver
        )

        return latest_ver

    def clean_template_env(self):
        """
        We have to clean everything in case there was previously failed
        create template task
        """
        templ_name = TEMPL_NAME.format(
            flow=self.args.flow,
            branch=self.args.branch,
            fedora_version=self.args.fedora_ver
        )
        templ_vm_name = templ_name + '_template'
        box_name = 'f{}'.format(self.args.fedora_ver)
        libvirt_vol_name = '{}.img'.format(templ_vm_name)

        subprocess.run(['virsh', 'destroy', templ_vm_name])
        subprocess.run(['virsh', 'undefine', templ_vm_name])
        subprocess.run(['vagrant', 'box', 'remove', '--force', box_name])
        subprocess.run(['virsh', 'vol-delete', '--pool', 'default',
                        libvirt_vol_name])
        try:
            shutil.rmtree(os.path.join('/tmp', templ_name))
        except OSError:
            pass

    def build_new_template(self):
        inv_path = 'ansible/hosts/runner_localhost'
        playbook_path = 'ansible/create_template_box.yml'

        os.chmod(os.path.join(self.args.prci_repo_path,
                              'keys/vagrant'), 0o0600)
        os.chmod(os.path.join(self.args.prci_repo_path,
                              'keys/freeipa_pr_ci_insecure'), 0o0600)

        try:
            logger.info('Started playbook %s', playbook_path)
            res = subprocess.check_output([
                    'ansible-playbook',
                    '-i', inv_path,
                    playbook_path,
                    '-e', 'fedora_version={}'.format(self.args.fedora_ver),
                    '-e', 'git_branch={}'.format(self.args.branch),
                    '-e', 'flow={}'.format(self.args.flow),
                ], cwd=self.args.prci_repo_path)
            return res.decode()
        except subprocess.CalledProcessError:
            logger.error('Ansible command failed with: %s', res.decode())

    def commit_new_prci_config_file(self):
        """
        Updates the .freeipa-pr-ci.yaml file with the content
        of the --prci_config provided file.
        """
        repo = Repo(self.args.repo_path)

        self.delete_local_branch()

        # creates new branch using the identifier as the name
        repo.git.checkout('-b', self.args.id)

        current_prci_test_config = os.path.join(self.args.repo_path,
                                                FREEIPA_PRCI_CONFIG_FILE)

        # changing the file that FREEIPA_PRCI_CONFIG_FILE points to
        os.unlink(current_prci_test_config)
        os.symlink(self.args.prci_config, current_prci_test_config)

        repo.git.add(FREEIPA_PRCI_CONFIG_FILE)
        repo.git.commit('-m', DEFAULT_COMMIT_MSG)
        repo.git.push("-u", MYGITHUB_REMOTE_REF, self.args.id)

    def commit_prci_versions_bump(self):
        repo = Repo(self.args.repo_path)

        self.delete_local_branch()

        # creates new branch using the identifier as the name
        repo.git.checkout('-b', self.args.id)
        repo.git.add(self.args.prci_def_dir)
        repo.git.commit('-m', DEFAULT_COMMIT_MSG)
        repo.git.push("-u", MYGITHUB_REMOTE_REF, self.args.id)

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

    def get_prci_defs(self):
        for file in os.scandir(
                os.path.join(self.args.repo_path, PRCI_DEF_DIR)):
            yield file.path

    def bump_prci_version(self, templ_ver):
        templ_name = 'freeipa/'+TEMPL_NAME.format(
            flow=self.args.flow,
            branch=self.args.branch,
            fedora_version=self.args.fedora_ver
        )
        for file in self.get_prci_defs():
            yaml_data = load_yaml(file)
            template = self.get_templ_list(yaml_data)
            if template['name'] == templ_name:
                template['version'] = templ_ver
                yaml = ruamel.yaml.YAML()
                dump_yaml(file, yaml_data)
            else:
                logger.info('No template found in %s', file)

    def close_older_pr(self):
        refs = {r.ref: r for r in self.repo.refs()}
        ref_uri = '{}{}'.format(REF_FORMAT, self.args.id)
        try:
            ref = refs[ref_uri]
            ref.delete()
            logger.debug("Older branch %s deleted in upstream", self.args.id)
        except KeyError:
            pass

    def rebase_branch(self):
        repo = Repo(self.args.repo_path)

        try:
            repo.git.remote('add', UPSTREAM_REMOTE_REF, REMOTE_REPO)
        except git.exc.GitCommandError:
            # the remote is already configured
            pass

        repo.git.fetch(UPSTREAM_REMOTE_REF)
        repo.git.checkout(self.args.branch)
        repo.git.pull(UPSTREAM_REMOTE_REF, self.args.branch)
        repo.git.push(MYGITHUB_REMOTE_REF, self.args.branch)

    def delete_local_branch(self):
        repo = Repo(self.args.repo_path)
        repo.git.checkout(self.args.branch)
        try:
            repo.git.branch("-D", self.args.id)
        except:
            pass

    def open_template_pr(self):
        # FIXME: we need to check if the latest nightly repo is in
        # 'successfull' state
        self.clean_template_env()
        # FIXME: capture ansible output to get newest template component
        # versions and put the info to PR description
        res = self.build_new_template()
        self.close_older_pr()
        self.rebase_branch()
        latest_ver = self.get_newest_templ_ver()
        self.bump_prci_version(latest_ver)
        self.commit_prci_versions_bump()

        pr_title = '[{}] PRCI template auto'.format(self.args.id)

        owner = ('freeipa' if self.args.pr_against_upstream
                 else self.repo.owner.login)
        logger.debug("A new PR against %s/freeipa will be created with "
                     "the title %s", owner, pr_title)
        self.create_pr(pr_title)

    def open_nightly_pr(self):
        # before opening a new PR, we close the old one with the same
        # identifier. The PR list shoud have only one open PR.
        self.close_older_pr()
        self.rebase_branch()
        self.commit_new_prci_config_file()
        pr_title = '[{}] Nightly PR'.format(self.args.id)
        owner = ('freeipa' if self.args.pr_against_upstream
                 else self.repo.owner.login)
        logger.debug("A new PR against %s/freeipa will be created with "
                     "the title %s", owner, pr_title)
        self.create_pr(pr_title)

    def create_pr(self, pr_title):
        try:
            if self.args.pr_against_upstream:
                users_head = '{}:{}'.format(self.repo.owner.login,
                                            self.args.id)
                pr = self.upstream_repo.create_pull(pr_title, self.args.branch,
                                                    users_head)
            else:
                # will open a PR against user's fork
                pr = self.repo.create_pull(pr_title, self.args.branch,
                                           self.args.id)

            logger.info("PR %s created", pr.number)
        except github3.GitHubError as error:
            logger.error(error.errors)
        finally:
            self.delete_local_branch()

    def run(self):
        fnc = getattr(self, self.args.command)
        logger.debug('Executing %s command', self.args.command)
        return fnc()


def create_parser():
    parent_parser = argparse.ArgumentParser(add_help=False)

    parent_parser.add_argument(
        '--flow', type=str, required=True,
        help='Flow name: ci or pki'
    )

    parent_parser.add_argument(
        '--branch', type=str, required=True,
        help='Branch name to open PR against it'
    )

    parent_parser.add_argument(
        '--id', type=str, required=True,
        help='PR identifier'
    )

    parent_parser.add_argument(
        '--config', type=config_file, required=True,
        help='YAML file with complete configuration.',
    )

    parent_parser.add_argument(
        '--repo_path', type=str, required=True,
        help='freeIPA repo path'
    )

    def __string_to_bool(value):
        if value.lower() in ['yes', 'true', 't', 'y', '1']:
            return True
        elif value.lower() in ['no', 'false', 'f', 'n', '0']:
            return False
        raise argparse.ArgumentTypeError('Boolean value expected.')

    parent_parser.add_argument(
        '--pr_against_upstream', type=__string_to_bool, required=True,
        help="Should the PR be open against the upstream repo? Use False for "
             "opening against your own freeipa repo"
    )

    parser = argparse.ArgumentParser(add_help=False)
    commands = parser.add_subparsers(dest='command')

    nightly = commands.add_parser('open_nightly_pr', parents=[parent_parser],
                                  description="Opens a PR for Nightly Tests")

    nightly.add_argument(
        '--prci_config', type=str, required=True,
        help="Relative path to PR CI test definition (yaml) file in "
             "FreeIPA repo. E.g: ipatests/prci_definitions/gating"
    )

    template = commands.add_parser(
        'open_template_pr', parents=[parent_parser],
        description="Opens a PR for bumping PRCI template version"
    )

    template.add_argument(
        '--prci_def_dir', type=str, required=True,
        help='PRCI definitions relative path in freeipa repo'
    )

    template.add_argument(
        '--fedora_ver', type=int, required=True,
        help='Fedora version'
    )

    template.add_argument(
        '--prci_repo_path', type=str, required=True,
        help='freeIPA PRCI repo path'
    )

    template.add_argument(
        '--atlas_config', type=str, required=True,
        help='Vagrant atlas config path'
    )

    return parser


def config_file(path):
    config = load_yaml(path)

    fields_required = ['repository', 'credentials']
    for field in fields_required:
        if field not in config:
            raise argparse.ArgumentTypeError(
                'Missing required section {} in config file', field)
    return config


def main():
    parser = create_parser()
    args = parser.parse_args()

    config = args.config
    creds = config['credentials']
    repository = config['repository']

    logger.debug('Running Open and Close PR Tool against %s/%s repo',
                 repository['owner'], repository['name'])

    automated_pr = AutomatedPR(creds['token'], repository, args)
    automated_pr.run()


if __name__ == '__main__':
    main()
