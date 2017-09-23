#!/usr/bin/python3
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

import argparse
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


def create_parser():
    parser = argparse.ArgumentParser(description='PR CI test control tool')
    commands = parser.add_subparsers(dest='cmd')
    
    list_cmd = commands.add_parser('list')
    list_cmd.add_argument('PR_NUM', type=int)
    
    rerun_cmd = commands.add_parser('rerun')
    rerun_cmd.add_argument('PR_NUM', type=int)

    rerun_opts = rerun_cmd.add_mutually_exclusive_group(required=True)
    rerun_opts.add_argument('--task')
    rerun_opts.add_argument('--all', action='store_true')
    rerun_opts.add_argument('--state', choices=['error', 'failure', 'pending', 'success'])

    return parser


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
        try:
            func = getattr(self, 'cmd_{}'.format(args.cmd))
        except AttributeError as exc:
            raise ValueError("unknown command {}".format(args.cmd))

        return func(args)

    def cmd_list(self, args):
        pull = self.repo.pull_request(args.PR_NUM)

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

    def cmd_rerun(self, args):
        pull = self.repo.pull_request(args.PR_NUM)

        contexts = {}
        for status in self.repo.commit(pull.head.sha).statuses():
            if status.context not in contexts:
                contexts[status.context] = status.state

        if args.task:
            if args.task not in contexts:
                raise ValueError('unknown test {}'.format(args.task))

            recreate = [args.task]

        elif args.all:
            recreate = contexts.keys()
        elif args.state:
            recreate = [c for c in contexts if contexts[c] == args.state]

        for context in recreate:
            self.repo.create_status(
                sha=pull.head.sha,
                state='pending',
                description='unassigned',
                context=context,
            )


if __name__ == '__main__':
    parser = create_parser()
    args = parser.parse_args()

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
        parser.print_help()
        exit(2)
