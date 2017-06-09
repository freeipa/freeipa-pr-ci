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
import yaml
import time


RACE_TIMEOUT = 10


class NoTaskAvailable(Exception):
    pass


class TaskAlreadyTaken(Exception):
    pass


def get_pull_priority(p):
    priority_prefix = 'priority:'
    for label in p.issue().labels():
        if label.name.startswith(priority_prefix):
            return int(label.name[len(priority_prefix):])
    else:
        return 0


class Status(object):
    @classmethod
    def create(cls, repo, pull, context, description, target_url, state):
        sha = repo.commit(pull.head.sha).sha
        repo.create_status(sha, state, target_url, description, context)
        return cls(repo, pull, context)

    def __init__(self, repo, pull, context):
        self.repo = repo
        self.pull = pull
        self.context = context

        for status in repo.commit(pull.head.sha).statuses():
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


class PullQueue(object):

    def __init__(self, repo):
        self.repo = repo

    def __iter_pull_without_tasks(self):
        for pull in self:
            if len(list(self.repo.commit(pull.head.sha).statuses())) == 0:
                yield pull

    def __iter__(self):
        for pull in sorted(self.repo.pull_requests(), reverse=True,
                            key=get_pull_priority):
            yield pull


class TaskQueue(collections.Iterator):
    def __init__(self, repo, tasks_config_path, job_cls):
        self.repo = repo
        self.job_cls = job_cls
        with open(tasks_config_path) as tc:
            self.tasks_conf = yaml.load(tc)

    def create_tasks_for_pulls(self):
        for pull in PullQueue(self.repo):
            if len(Statuses(self.repo, pull, self.tasks_conf.keys())):
                continue
            for task in self.tasks_conf:
                Status.create(self.repo, pull, task, 'unassigned', '',
                              'pending')

    def next(self):
        for pull in PullQueue(self.repo):
            tasks = []
            for status in Statuses(self.repo, pull, self.tasks_conf).values():
                if (status.state != 'pending' or
                    status.description != 'unassigned'):
                        continue

                task = Task(status, self.tasks_conf[status.context], self.job_cls)
                if task.dependencies_done():
                    tasks.append(task)

            if tasks:
                return max(tasks, key=lambda t: t.priority)

        raise StopIteration()


class Task(object):
    def __init__(self, status, conf, job_cls):
        self.status = status
        self.repo = status.repo
        self.pull = status.pull
        self.refspec = 'pull/{}/head'.format(self.pull.number)
        self.name = status.context

        self.priority = conf['priority']
        self.requires = conf['requires']
        self.job = job_cls(conf['job'], self.refspec)

    def dependencies_done(self):
        for dep in self.requires:
            if Status(self.repo, self.pull, dep).state != 'success':
                return False
        return True

    def take(self, runner_id):
        desc = 'Taken by {}'.format(runner_id)
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
