#!/usr/bin/python3

import os
import github3
import argparse
import logging
import shutil
import yaml
from cachecontrol.adapter import CacheControlAdapter
import git
from git import Repo


REF_FORMAT = 'refs/heads/'
DEFAULT_COMMIT_MSG = 'automated commit'
FREEIPA_PRCI_CONFIG_FILE = '.freeipa-pr-ci.yaml'
REMOTE_REPO = 'https://github.com/freeipa/freeipa.git'
UPSTREAM_REMOTE_REF = 'upstream'
MYGITHUB_REMOTE_REF = 'mygithub'

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
consoleHandler = logging.StreamHandler()
consoleHandler.setLevel(logging.INFO)
logger.addHandler(consoleHandler)


def load_yaml(yml_path):
    try:
        with open(yml_path) as yml_file:
            return yaml.load(yml_file)
    except IOError as exc:
        raise argparse.ArgumentTypeError(
            'Failed to open {}: {}'.format(yml_path, exc))
    except yaml.YAMLError as exc:
        raise argparse.ArgumentTypeError(
            'Failed to parse YAML from {}: {}'.format(yml_path, exc))


class AutomatedPR(object):

    def __init__(self, github_token, repo):
        github = github3.login(token=github_token)
        github.session.mount('https://api.github.com', CacheControlAdapter())
        self.repo = github.repository(repo['owner'], repo['name'])
        self.upstream_repo = github.repository('freeipa', 'freeipa')

    def commit_new_prci_config_file(self, new_prci_config, args):
        """
        Updates the .freeipa-pr-ci.yaml file with the content
        of the --prci_config provided file.
        """
        prci_config_file = os.path.join(args.repo_path,
                                        FREEIPA_PRCI_CONFIG_FILE)

        shutil.copy(prci_config_file, new_prci_config)

        repo = Repo(args.repo_path)
        repo.git.add(FREEIPA_PRCI_CONFIG_FILE)
        repo.git.commit('-m', DEFAULT_COMMIT_MSG)
        repo.git.push(MYGITHUB_REMOTE_REF, args.id)

    def close_older_pr(self, identifier):
        refs = {r.ref:r for r in self.repo.refs()}
        ref_uri = '{}{}'.format(REF_FORMAT, identifier)
        ref = refs[ref_uri]
        ref.delete()
        logger.debug("Branch %s deleted", identifier)

    def rebase_branch(self, base_branch, identifier, git_repo_path):
        repo = Repo(git_repo_path)

        try:
            repo.git.remote('add', UPSTREAM_REMOTE_REF, REMOTE_REPO)
        except git.exc.GitCommandError:
            # the remote is already configured
            pass

        repo.git.fetch(UPSTREAM_REMOTE_REF)
        repo.git.checkout('{}/{}'.format(UPSTREAM_REMOTE_REF, base_branch))

        # creates new branch using the identifier as the name
        repo.git.checkout('-b', identifier)
        repo.git.push(MYGITHUB_REMOTE_REF, '-u', identifier)

    def open_pr(self, args):
        # before opening a new PR, we close the old one with the same
        # identifier. The PR list shoud have only one open PR.
        self.close_older_pr(args.id)

        self.rebase_branch(args.branch, args.id, args.repo_path)

        self.commit_new_prci_config_file(args.prci_config, args)

        pr_title = '[{}] Nightly PR'.format(args.id)

        logger.debug("A new PR against %s/%s will be created with "
                     "the title %s", self.repo.owner.login,
                     self.repo.source.name, pr_title)

        try:
            if args.pr_against_upstream:
                base = 'freeipa:{}'.format(args.branch)
                pr = self.upstream_repo.create_pull(pr_title, base, args.id)
            else:
                # will open a PR against user's fork
                pr = self.repo.create_pull(pr_title, args.branch, args.id)

            logger.info("PR %s created", pr.number)
        except github3.GitHubError as error:
            logger.error(error.errors)

    def run(self, args):
        fnc = getattr(self, args.command)
        logger.debug('Executing %s command', args.command)
        return fnc(args)


def create_parser():
    parser = argparse.ArgumentParser(description='')
    commands = parser.add_subparsers(dest='command')

    commands.add_parser('open_pr', description="Opens a PR for Nightly Tests")

    parser.add_argument(
        '--config', type=config_file, required=True,
        help='YAML file with complete configuration.',
    )

    parser.add_argument(
        '--prci_config', type=str, required=True,
        help='Path to a new .freeipa-pr-ci.yml file'
    )

    parser.add_argument(
        '--branch', type=str, required=True,
        help='Branch name to open PR against it'
    )

    parser.add_argument(
        '--id', type=str, required=True,
        help='PR identifier'
    )

    parser.add_argument(
        '--repo_path', type=str, required=True,
        help='freeIPA repo path'
    )

    parser.add_argument(
        '--pr_against_upstream', type=bool, required=True,
        help="Should the PR be open against the upstream repo?. Use False for "
             "opening agaist your own freeipa repo"
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

    automated_pr = AutomatedPR(creds['token'], repository)
    automated_pr.run(args)


if __name__ == '__main__':
    main()
