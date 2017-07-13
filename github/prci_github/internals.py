#!/usr/bin/python

"""
                 |-------------------------|   |-------------|                                   
                 | PullQueue               |   | TaskQueue   |                                   
                 |                         |   |             |                                   
    =============| .get_pull_without_tasks |   | .take()     |===\                                
    =            |                         |   |             |   =                                
    =            |-------------------------|   |-------------|   =                                
    =                                                            =                                
    v                                                            v                                
|--------------|                                               |--------------|                     
| PullRequest  |                                               | Task         |                     
| .id          |<----------------------------------------------| .pull        |                     
|              |                      /------------------------| .commit      |                     
|              |    |------------|    |                    /---| .status      |                     
| .head.sha    |--->| RepoCommit |    |                    |   | .job         |---\                   
|--------------|    | .sha       |<---/                    |   |--------------|   |                   
                    |            |                         |                      |                   
                    |            |                         |                      |                   
                    |            |    |--------------|     |                      |                   
                    | .statuses  |--->||--------------|    |                      |                   
                    |------------|    || Status       |    |                      |                   
                                      ||              |    |                      |  
                                      || .description |    |   |---------------|  |
                                      || .context     |<---/   | Job           |<-/
                                      || .state       |        |               |
                                      || .target_url  |        | .run          |
                                      ||              |        | .collect_logs |
                                       |--------------|        |---------------|
"""
import abc
import collections
import logging
import time
import yaml

from .adapter import GitHubAdapter


RACE_TIMEOUT = 10
CREATE_TIMEOUT = 5
RERUN_LABEL = 're-run'


logger = logging.getLogger(__name__)


class TaskAlreadyTaken(Exception):
    pass


class Status(object):
    @classmethod
    def create(cls, repo, pull, context, description, target_url, state):
        sha = repo.commit(pull.pull.head.sha).sha
        s = repo.create_status(sha, state, target_url, description, context)

        # invalidate cache for statuses on this commit
        for k, adapter in repo.session.adapters.items():
            if isinstance(adapter, GitHubAdapter):
                adapter.cache.data.pop(s.url, None)
                break

        last_e = RuntimeError()
        for _ in range(CREATE_TIMEOUT):
            try:
                return cls(repo, pull, context)
            except Exception as e:
                last_e = e
                time.sleep(1)
        else:
            raise last_e

    def __init__(self, repo, pull, context):
        self.repo = repo
        self.pull = pull
        self.context = context

        for status in repo.commit(pull.pull.head.sha).statuses():
            if status.context == self.context:
                break
        else:
            raise ValueError('No status with context {}'.format(context))

        self.description = status.description
        self.target_url = status.target_url
        self.state = status.state


class Statuses(collections.Mapping):
    def __init__(self, repo, pull, contexts):
        self.repo = repo
        self.pull = pull
        self.contexts = contexts

    def __getitem__(self, key):
        try:
            return Status(self.repo, self.pull, key)
        except ValueError:
            raise KeyError(key)

    def __len__(self):
        l = 0
        for context in self.contexts:
            try:
                Status(self.repo, self.pull, context)
            except ValueError:
                pass
            else:
                l += 1

        return l

    def __iter__(self):
        for context in self.contexts:
            try:
                Status(self.repo, self.pull, context)
            except ValueError:
                pass
            else:
                yield context

    def values(self):
        ret = []
        for context in self.contexts:
            try:
                ret.append(Status(self.repo, self.pull, context))
            except ValueError:
                pass

        return ret

    def items(self):
        ret = []
        for context in self.contexts:
            try:
                ret.append((context, Status(self.repo, self.pull, context),))
            except ValueError:
                pass

        return ret


class Labels(collections.MutableSet):
    def __init__(self, pull):
        self.pull = pull

    def __contains__(self, label):
        return label in [l.name for l in self.pull.issue().labels()]

    def __iter__(self):
        for label in self.pull.issue().labels():
            yield label.name

    def __len__(self):
        return len([l for l in self.pull.issue().labels()])

    def add(self, label):
        self.pull.issue().add_labels(label)

    def discard(self, label):
        self.pull.issue().remove_label(label)


class PullRequest(object):
    def __init__(self, pull, repo):
        self.pull = pull
        self.repo = repo

    @property
    def labels(self):
        return Labels(self.pull)

    def tasks(self, tasks_conf, job_cls):
        return Tasks(self, self.repo, tasks_conf, job_cls)


class PullRequests(collections.Iterator):
    def __init__(self, repo):
        self.repo = repo
        self.pull_requests = self.repo.pull_requests()

    def next(self):
        return PullRequest(next(self.pull_requests), self.repo)


class Task(object):
    def __init__(self, status, conf, job_cls):
        self.status = status
        self.repo = status.repo
        self.pull = status.pull
        self.refspec = 'pull/{}/head'.format(self.pull.pull.number)
        self.name = status.context

        self.priority = conf['priority']
        self.requires = conf['requires']
        self.job = job_cls(conf['job'], self.refspec)


    def dependencies_done(self):
        for dep in self.requires:
            if Status(self.repo, self.pull, dep).state != 'success':
                return False
        return True

    def can_run(self):
        if (self.status.state == 'pending' and
            self.status.description == 'unassigned'):
                return self.dependencies_done()
        return False

    def take(self, runner_id):
        desc = 'Taken by {}'.format(runner_id)
        logger.debug('Attempting to take task')
        Status.create(self.repo, self.pull, self.name, desc, '', 'pending')
        time.sleep(RACE_TIMEOUT)
        status = Status(self.repo, self.pull, self.name)

        if status.description != desc:
            raise TaskAlreadyTaken(status.description)

    def execute(self):
        depends_results = {}
        for dep in self.requires:
            status = Status(self.repo, self.pull, dep)
            depends_results[dep] = JobResult(
                status.state, status.description, status.target_url)

        try:
            result = self.job(depends_results)
        except Exception as e:
            state = 'error'
            description = getattr(e, 'description', str(e))
            url = getattr(e, 'url', '')
        else:
            state = result.state
            description = result.description
            url = result.url

        Status.create(self.repo, self.pull, self.name, description, url, state)


class Tasks(collections.Set, collections.Mapping):
    def __init__(self, pull, repo, tasks_conf, job_cls):
        self.pull = pull
        self.repo = repo
        self.tasks_conf = tasks_conf
        self.job_cls = job_cls

    def __len__(self):
        return len(Statuses(self.repo, self.pull, self.tasks_conf.keys()))

    def __iter__(self):
        for task in self.tasks_conf:
            try:
                status = Status(self.repo, self.pull, task)
            except ValueError:
                # ignore missing
                pass
            else:
                yield Task(status, self.tasks_conf[task], self.job_cls)

    def __getitem__(self, context):
        try:
            status = Status(self.repo, self.pull, context)
        except ValueError:
            raise KeyError(context)
        else:
            return Task(status, self.tasks_conf[task], self.job_cls)

    def __bool__(self):
        return bool(len(self))

    def create(self):
        logger.debug("Creating tasks for PR {}".format(self.pull.pull.number))
        for task in self.tasks_conf:
            logger.debug("PR {}: {}".format(self.pull.pull.number, task))
            Status.create(self.repo, self.pull, task, 'unassigned', '', 'pending')
        logger.debug("Creating tasks for PR {} done.".format(self.pull.pull.number))


class TaskQueue(collections.Iterator):
    def __init__(self, repo, tasks_config_path, job_cls):
        self.repo = repo
        self.job_cls = job_cls
        with open(tasks_config_path) as tc:
            self.tasks_conf = yaml.load(tc)

    def create_tasks_for_pulls(self):
        """
        Generate CI tasks represented by GitHub Statuses [1]

        The tasks are generated when:
        a. there's RERUN_LABEL on the PR
        b. there're no tasks yet

        [1] https://developer.github.com/v3/repos/statuses/
        """
        for pull in PullRequests(self.repo):
            logger.debug("PR {}".format(pull.pull.number))
            tasks = pull.tasks(self.tasks_conf, self.job_cls)
            if not tasks:
                logger.debug('Creating tasks for PR {}'.format(pull.pull.number))
                tasks.create()
            elif RERUN_LABEL in pull.labels:
                logger.debug('Recreating tasks for PR {}'.format(pull.pull.number))
                pull.labels.discard(RERUN_LABEL)
                tasks.create()

    def next(self):
        """
        Return next task for processing

        From tasks that are available for execution the one with maximum
        priority is returned.
        """
        tasks = []
        for pull in PullRequests(self.repo):
            for task in pull.tasks(self.tasks_conf, self.job_cls):
                if task.can_run():
                    tasks.append(task)

        if tasks:
            return max(
                tasks,
                key=lambda t: ('prioritize' in t.pull.labels, t.priority),
            )
        else:
            raise StopIteration()


class JobResult(object):
    valid_states = ('success', 'error', 'failure',)

    def __init__(self, state, description=None, url=None):
        if state not in self.valid_states:
            raise ValueError('invalid state: {}'.format(state))
        self.state = state
        self.description = description
        self.url = url


class AbstractJob(collections.Callable):
    __metaclass__ = abc.ABCMeta
    def __init__(self, cmd, build_target):
        """
        @param cmd - job specific data from task definition
        @param build_target - tuple of git repo url and refspec
                              git clone build_target[0]
                              git fetch origin build:build_target[1]
                              git checkout build
        """
        self.cmd = cmd
        self.target = build_target

    @abc.abstractmethod
    def __call__(self, depends_results={}):
        """
        @param depends_results - dict of task_name: JobResult
        @returns JobResult instance
        """
        return JobResult('success', 'description', 'url')
