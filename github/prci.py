#!/usr/bin/python3

import argparse
import logging
import os
import raven
import signal
import subprocess
import sys
import time
import yaml

import github3

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from tasks import TimeoutException
from prci_github import TaskQueue, AbstractJob, TaskAlreadyTaken, JobResult
from prci_github.adapter import GitHubAdapter


SENTRY_URL = 'https://d24d8d622cbb4e2ea447c9a64f19b81a:4db0ce47706f435bb3f8a02a0a1f2e22@sentry.io/193222'
NO_TASK_BACKOFF_TIME = 5
logger = logging.getLogger(__name__)  # pylint: disable=invalid-name


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
        except subprocess.CalledProcessError as err:
            if err.returncode == 1:
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
            description = '{type_}: {msg}'.format(type_=type(exc).__name__,
                                                  msg=str(exc))
            state = 'error'

            sentry_report_exception({
                'module': 'tasks'})
        else:
            description = job.description
            if job.returncode == 0:
                state = 'success'
            else:
                state = 'failure'

        return JobResult(state, description, job.remote_url)


def create_parser():
    def log_level(level_name):
        try:
            return getattr(logging, level_name)
        except AttributeError:
            raise argparse.ArgumentTypeError(
                '{} is not valid logging level'.format(level_name))

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
        '--tasks', type=str, required=True,
        help='Path to YAML file with definiton of tasks, from repo root',
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


def sentry_report_exception(context=None):
    sentry = raven.Client(SENTRY_URL)

    if context is not None:
        with sentry.context:
            sentry.context.merge(context)
    try:
        sentry.captureException()
    finally:
        sentry.context.clear()


if __name__ == '__main__':
    parser = create_parser()
    args = parser.parse_args()

    runner_id = args.id
    creds = yaml.load(args.credentials)
    tasks_file = args.tasks

    logging.basicConfig(level=args.log_level)

    github = github3.login(token=creds['token'])
    github.session.mount('https://api.github.com', GitHubAdapter())

    repo = github.repository(creds['user'], creds['repo'])
    task_queue = TaskQueue(repo, tasks_file, JobDispatcher)

    handler = ExitHandler()

    signal.signal(signal.SIGINT, handler.finish)
    signal.signal(signal.SIGTERM, handler.abort)

    while not handler.done:
        try:
            update_code()

            task_queue.create_tasks_for_pulls()

            try:
                task = next(task_queue)
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
        except Exception:
            sentry_report_exception({
                'module': 'github'})
