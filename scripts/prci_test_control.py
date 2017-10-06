#!/usr/bin/python3
"""PR CI Test Control Tool

Usage:
  prci_test_control.py list <pr_number>
  prci_test_control.py rerun --all <pr_number>
  prci_test_control.py rerun --task <task> <pr_number>
  prci_test_control.py rerun --state (error | failure | pending | success) <pr_number>
  prci_test_control.py (-h | --help)
  prci_test_control.py --version

Options:
  -h --help     Show this screen.
  --version     Show version.

"""

"""
$ # configuration file
$ cat ~/.config/prci_test_control.yaml
# credentials, either (username and password) or token is required
username: testuser
password: supersecret
token: pseudorandomapplicationtoken
# repository specification
owner: freeipa
repo: freeipa
"""

from docopt import docopt
from xtermcolor import colorize
import github3
import os
import yaml

state2color = {
    'error': 0xcb2431,
    'failure': 0xcb2431,
    'pending': 0xdbab09,
    'success': 0x28a745,
}


class TestControl(object):
    def __init__(self, cfg_path):
        try:
            cfg = yaml.load(open(cfg_path))
        except (IOError, yaml.parser.ParserError) as exc:
            raise ValueError(exc)

        self.gh = github3.login(
            username=cfg.get('username'),
            password=cfg.get('password'),
            token=cfg.get('token'),
        )

        if not self.gh:
            raise ValueError('wrong credentials')

        try:
            owner = cfg['owner']
            repo = cfg['repo']
        except KeyError as exc:
            raise ValueError('missing {}'.format(exc))

        self.repo = self.gh.repository(owner, repo)
        if not self.repo:
            raise ValueError('wrong repository')

    def __call__(self, args):

        if args['list'] and args['<pr_number>']:
            return self.cmd_list(args['<pr_number>'])

        if args['rerun'] and args['<pr_number>']:

            params = {'all': False, 'task': None, 'state': None}

            if args['--all']:
                params['all'] = True

            if args['--task'] and args['<task>']:
                params['task'] = args['<task>']

            if args['--state']:
                params['state'] = ''
                params['state'] += 'error' if args['error'] else ''
                params['state'] += 'failure' if args['failure'] else ''
                params['state'] += 'pending' if args['pending'] else ''
                params['state'] += 'success' if args['success'] else ''

            return self.cmd_rerun(args['<pr_number>'], params)

    def cmd_list(self, pr_num):
        pull = self.repo.pull_request(pr_num)

        contexts = set()
        for status in self.repo.commit(pull.head.sha).statuses():
            if status.context in contexts:
                continue

            contexts.add(status.context)
            print(
                colorize(
                    "{:<8}".format(status.state),
                    rgb=state2color[status.state]
                ) +
                "{s.context:<30.30} {s.description:<50.50} {s.target_url}"
                "".format(s=status)
            )

    def cmd_rerun(self, pr_num, params):
        pull = self.repo.pull_request(pr_num)

        contexts = {}
        for status in self.repo.commit(pull.head.sha).statuses():
            if status.context not in contexts:
                contexts[status.context] = status.state

        if params['task']:
            if params['task'] not in contexts:
                raise ValueError('unknown test {}'.format(params['task']))

            recreate = [params['task']]

        elif params['all']:
            recreate = contexts.keys()
        elif params['state']:
            recreate = [c for c in contexts if contexts[c] == params['state']]

        for context in recreate:
            self.repo.create_status(
                sha=pull.head.sha,
                state='pending',
                description='unassigned',
                context=context,
            )


if __name__ == '__main__':

    args = docopt(__doc__, version='0.0.1')

    try:
        tc = TestControl(
            os.path.expanduser('~/.config/prci_test_control.yaml'))
    except ValueError as exc:
        print(exc)
        exit(1)

    try:
        tc(args)
    except ValueError as exc:
        print(exc)
        exit(2)
