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

import os
import docopt
from xtermcolor import colorize
import github3
import yaml

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

state2color = {
    'error': 0xcb2431,
    'failure': 0xcb2431,
    'pending': 0xdbab09,
    'success': 0x28a745,
}


class TestControl(object):
    CMDS = ('list', 'rerun',)
    STATES = ('error', 'failure', 'pending', 'success',)

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
        cmd = [c for c in self.CMDS if args[c]][0]
        try:
            func = getattr(self, 'cmd_{}'.format(cmd))
        except AttributeError:
            raise ValueError("unknown command {}".format(cmd))

        return func(args)

    def cmd_list(self, args):
        pull = self.repo.pull_request(args['<pr_number>'])

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
                "{s.context:<45.45} {s.description:<40.40} {s.target_url}"
                "".format(s=status)
            )

    def cmd_rerun(self, args):
        pull = self.repo.pull_request(args['<pr_number>'])

        contexts = {}
        for status in self.repo.commit(pull.head.sha).statuses():
            if status.context not in contexts:
                contexts[status.context] = status.state

        if args['--task']:
            if args['<task>'] not in contexts:
                raise ValueError('unknown test {}'.format(args['<task>']))

            recreate = [args['<task>']]

        elif args['--all']:
            recreate = contexts.keys()
        elif args['--state']:
            state = [s for s in self.STATES if args[s]][0]
            recreate = [c for c in contexts if contexts[c] == state]

        for context in recreate:
            self.repo.create_status(
                sha=pull.head.sha,
                state='pending',
                description='unassigned',
                context=context,
            )


def main():
    args = docopt.docopt(__doc__, version='0.0.1')

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


if __name__ == '__main__':
    main()
