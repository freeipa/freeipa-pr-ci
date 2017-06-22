import argparse
import github3
from github3.null import NullObject
import logging
import signal
import subprocess
import sys
import time
import yaml

from prci_github import TaskQueue, AbstractJob, TaskAlreadyTaken, JobResult
from prci_github.adapter import GitHubAdapter


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


        cmd = self.cmd.format(target_refspec=self.target, **dep_results)

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
        '--credentials', type=file, required=True,
        help='YAML file containig at least user, token and repository',
    )
    parser.add_argument(
        '--tasks', type=file, required=True,
        help='YAML file with definiton of tasks',
    )
    parser.add_argument(
        '--log-level', type=log_level,
    )

    return parser


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
    tq = TaskQueue(repo, tasks_file.name, Job)

    handler = ExitHandler()

    signal.signal(signal.SIGINT, handler.finish)
    signal.signal(signal.SIGTERM, handler.abort)

    while not handler.done:
        tq.create_tasks_for_pulls()

        try:
            task = tq.next()
        except StopIteration:
            time.sleep(30)
            continue

        try:
            task.take(runner_id)
        except TaskAlreadyTaken:
            continue

        handler.register_task(task)
        task.execute()
        handler.unregister_task()
