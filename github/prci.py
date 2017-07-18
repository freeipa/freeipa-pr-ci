#!/usr/bin/python3

import argparse
import github3
import logging
import os
import signal
import subprocess
import sys
import time
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from tasks import TimeoutException
from prci_github import TaskQueue, AbstractJob, TaskAlreadyTaken, JobResult
from prci_github.adapter import GitHubAdapter


NO_TASK_BACKOFF_TIME = 5


class ExitHandler(object):
    done = False
    abort = False
    task = None

    def finish(self):
        if self.done:
            return self.abort()

        logger.info("Waiting for current task to finish. This may take long.")
        self.done = True

    def abort(self):
        if self.abort:
            return self.quit()

        if self.task:
            task.abort()
            logger.info("Waiting for aborted task to clean up. This may take few minutes.")

        self.abort = True

    def quit(self):
        logger.info("Quiting just now! No results will be reported.")
        sys.exit()

    def register_task(self, task):
        self.task = task

    def unregister_task(self):
        self.task = None


class Job(AbstractJob):
    def __call__(self, depends_results={}):
        url = None
        description = None

        dep_results = {}
        for task_name, result in depends_results.items():
            dep_results['{}_description'.format(task_name)] = result.description
            dep_results['{}_url'.format(task_name)] = result.url


        cmd = self.job.format(target_refspec=self.target, **dep_results)

        try:
            url = subprocess.check_output(cmd, shell=True)
        except subprocess.CalledProcessError as e:
            if e.returncode == 1:
                state = 'error'
                url = ''
            else:
                raise
        else:
            state = 'success'
            description = ''

        return JobResult(state, description, url)


class JobDispatcher(AbstractJob):
    def __init__(self, job, build_target):
        super(JobDispatcher, self).__init__(job, build_target)
        self.klass = getattr(
            __import__('tasks', fromlist=[self.job['class']]),
            self.job['class'])
        self.kwargs = self.job['args']
        self.kwarg_lookup = {
            'git_repo': build_target[0],
            'git_refspec': build_target[1]}

    def __call__(self, depends_results=None):
        if depends_results is not None:
            for task_name, result in depends_results.items():
                self.kwarg_lookup['{}_description'.format(task_name)] = \
                    result.description
                self.kwarg_lookup['{}_url'.format(task_name)] = result.url

        kwargs = {}
        for key, value in self.kwargs.items():
            if isinstance(value, str):
                value = value.format(**self.kwarg_lookup)
            kwargs[key] = value

        job = self.klass(**kwargs)
        try:
            job()
        except Exception as exc:
            description = '{type_}: {msg}'.format(type_=type(exc),
                                                  msg=str(exc))
            state = 'error'
        else:
            description = job.description
            if job.returncode == 0:
                state = 'success'
            else:
                state = 'failure'

        return JobResult(state, description, job.remote_url)


def create_parser():
    def log_level(l):
        try:
            return getattr(logging, l)
        except AttributeError:
            raise argparse.ArgumentTypeError(
                '{} is not valid logging level'.format(l))

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--id', type=str, required=True,
        help='Unique runner ID',
    )
    parser.add_argument(
        '--credentials', type=argparse.FileType('r'), required=True,
        help='YAML file containig at least user, token and repository',
    )
    parser.add_argument(
        '--tasks', type=argparse.FileType('r'), required=True,
        help='YAML file with definiton of tasks',
    )
    parser.add_argument(
        '--log-level', type=log_level,
    )

    return parser


def update_code():
    cmd = ['git', 'pull', 'origin', 'master']
    stdout = subprocess.check_output(cmd).decode('utf-8')
    if 'Already up-to-date' not in stdout:
        logger.info('Code change detected, reloading process.')
        os.execv(__file__, sys.argv)


if __name__ == '__main__':
    parser = create_parser()
    args = parser.parse_args()

    runner_id = args.id
    creds = yaml.load(args.credentials)
    tasks_file = args.tasks

    logging.basicConfig(level=args.log_level)

    gh = github3.login(token=creds['token'])
    gh.session.mount('https://api.github.com', GitHubAdapter())

    repo = gh.repository(creds['user'], creds['repo'])
    tq = TaskQueue(repo, tasks_file.name, JobDispatcher)

    handler = ExitHandler()

    signal.signal(signal.SIGINT, handler.finish)
    signal.signal(signal.SIGTERM, handler.abort)

    while not handler.done:
        update_code()

        tq.create_tasks_for_pulls()

        try:
            task = next(tq)
        except StopIteration:
            time.sleep(NO_TASK_BACKOFF_TIME)
            continue

        try:
            task.take(runner_id)
        except TaskAlreadyTaken:
            continue

        handler.register_task(task)
        task.execute()
        handler.unregister_task()
