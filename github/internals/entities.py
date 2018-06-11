import operator
import sys
from collections.abc import Callable as AbcCallable
from datetime import datetime, timedelta
from enum import Enum, unique
from random import randint
from time import sleep
from typing import Callable, ByteString, Dict, List, Text, Tuple, SupportsFloat

import psutil
import pytz
import yaml
from dateutil import parser
from github3 import GitHub
from github3.exceptions import ServerError
from requests.sessions import Session

import parse
import raven
from .gql import util, queries

from tasks import tasks
from tasks.common import TaskException

API_CHECK_TRIES = 5
API_CHECK_SLEEP = 7
GITHUB_DESCRIPTION_LIMIT = 139
RACE_TIMEOUT = 17
RERUN_PENDING = "pending for rerun"
TASK_TAKEN_FMT = "Taken by {runner_id} on {date}"
SENTRY_URL = (
    "https://d24d8d622cbb4e2ea447c9a64f19b81a:"
    "4db0ce47706f435bb3f8a02a0a1f2e22@sentry.io/193222"
)

# When runner reaches this remaining API limit value, it will sleep
# until the reset time will come.
EPHEMERAL_LIMIT = 60
STALE_TASK_EXTRA_TIME = 60


def sentry_report_exception(context: Dict):
    """Use Sentry's Python client (raven) to upload info about exceptions

    What Sentry is:
        Open-source error tracking that helps developers monitor and fix
        crashes in real time. Iterate continuously. Boost efficiency.
        Improve user experience.
        (https://sentry.io/welcome/)
    """
    sentry = raven.Client(SENTRY_URL)
    sentry.context.merge(context)

    try:
        sentry.captureException()
    finally:
        sentry.context.clear()


class CIEnum(Enum):
    """Ordinary enum with a fabric"""
    @classmethod
    def from_str(cls, s: Text) -> "CIEnum":
        """Fabric of CIEnum"""
        return cls._value2member_map_.get(s)


@unique
class Label(CIEnum):
    """Enum which represents the label of a pull request"""
    ACK = "ack"
    BLACKLIST = "blacklisted"
    POSTPONE = "postponed"
    RERUN = "re-run"
    REBASE = "needs rebase"
    PRIORITIZED = "prioritized"


@unique
class State(CIEnum):
    """Enum which represents the status of a commit"""
    PENDING = "PENDING"
    FAILURE = "FAILURE"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


class RateLimit(object):
    """Represents the GitHub API rate limit

    github3py returns a dict with two keys: resources and rate:

    {
        'rate': {'limit': 5000, 'remaining': 4911, 'reset': 1522063348},
        'resources': {
            'core': {'limit': 5000, 'remaining': 4911, 'reset': 1522063348},
            'graphql': {'limit': 5000, 'remaining': 4927, 'reset': 1522065504},
            'search': {'limit': 30, 'remaining': 30, 'reset': 1522063078}
        }
    }

    So to get the limit we're interested in we need to access the 'resources'
    dict and get an information.
    """

    # We don't use 'search' resource, so only 'core' and 'graphql' are valid
    valid_resources = ["core", "graphql"]

    def __init__(self, limit: int, remaining: int, reset_at: int) -> None:
        self.limit = limit
        self.remaining = remaining
        self.reset_at = reset_at

    @property
    def available(self) -> bool:
        return self.remaining >= EPHEMERAL_LIMIT

    def wait(self) -> None:
        if not self.available:
            reset_time = datetime.fromtimestamp(self.reset_at)
            now_time = datetime.now()
            sleep_time = reset_time - now_time

            sleep(sleep_time.total_seconds())

    @staticmethod
    def from_dict(data_dict: Dict) -> "RateLimit":
        """Fabric of RateLimit"""
        return RateLimit(
            limit=data_dict["limit"],
            remaining=data_dict["remaining"],
            reset_at=data_dict["reset"]
        )


class World(object):
    """Represents the outside world state"""
    def __init__(
        self, graphql_request: Callable, github_api: GitHub,
        session: Session, repo_owner: Text, repo_name: Text,
        runner_id: Text, tasks_path: Text, whitelist: List[Text]
    ) -> None:
        self.available_resources = AvailableResources()
        self.graphql_request = graphql_request
        self.github_api = github_api
        self.session = session
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.runner_id = runner_id
        self.tasks_path = tasks_path
        self.whitelist = whitelist
        self.instance = self

    def get_rate_limit(self, resource: Text=None) -> RateLimit:
        """Calls GitHub API and returns RateLimit instance"""
        if resource not in RateLimit.valid_resources:
            ValueError("Supported resources are graphql and core")

        return RateLimit.from_dict(
            self.github_api.rate_limit()["resources"][resource]
        )

    def poll_status(
        self, pr_number: int, task_name: Text
    ) -> "Status":
        """Gets commit status on GitHub using GraphQL API"""
        sleep(randint(3, 8))  # FIXME: We're polling too concurrently
        pr_query = queries.make_pull_request_query(
            self.repo_owner, self.repo_name, pr_number
        )
        self.check_graphql_limit()
        response = self.graphql_request(query=pr_query)

        data = util.get_data(response)
        repository = util.get_repository(data)
        pull_request = util.get_pull_request(repository)
        commit = util.get_last_commit(pull_request)
        statuses = util.get_statuses(commit)
        status = util.get_status(statuses, task_name)
        if not status:
            raise EnvironmentError("Can't parse status data.")

        return Status.from_dict(status)

    def create_status(
        self, task: "Task", state: State,
        description: Text, target_url: Text=""
    ) -> None:
        """Creates commit status on GitHub using REST API

        Raises:
            github3.exceptions.GitHubError, ValueError
        """
        if state not in Status.valid_states:
            raise ValueError("Can't create status. Wrong state.")

        self.check_rest_limit()
        self.github_api.repository(
            self.repo_owner, self.repo_name
        ).create_status(
            task.commit_sha, state.value.lower(),
            target_url, description, task.name
        )

    def __check_limit(self, resource: Text=None) -> None:
        error = None
        for _i in range(API_CHECK_TRIES):
            try:
                self.get_rate_limit(resource).wait()
                break
            except ServerError as e:
                error = e
                sleep(API_CHECK_SLEEP)
        else:
            if error is None:
                raise RuntimeError(
                    "Something really bad happened while checking API limit"
                )
            raise error


    def check_rest_limit(self) -> None:
        return self.__check_limit("core")

    def check_graphql_limit(self) -> None:
        return self.__check_limit("graphql")


class Topology(object):
    def __init__(
        self, name: Text=None, memory: SupportsFloat=None, cpu: int=None
    ) -> None:
        if memory is None:
            memory = AvailableResources.initial_memory

        self.memory = float(memory)
        self.name = name if name is not None else "undefined"
        self.cpu = cpu if cpu is not None else AvailableResources.initial_cpu

    def __eq__(self, other) -> bool:
        return all((
            self.name == other.name,
            self.memory == other.memory,
            self.cpu == other.cpu
        ))

    @staticmethod
    def from_dict(dict_data: Dict) -> "Topology":
        """Factory for Topology"""
        return Topology(
            name=dict_data.get("name"),
            memory=dict_data.get("memory"),
            cpu=dict_data.get("cpu")
        )


class AvailableResources(object):
    initial_cpu = psutil.cpu_count()
    initial_memory = psutil.virtual_memory().available / float(1024 ** 2)

    def __init__(self) -> None:
        self.cpu = AvailableResources.initial_cpu
        self.memory = AvailableResources.initial_memory

    def __str__(self) -> Text:
        return "{cpu} CPU, {memory}MB".format(
            cpu=self.cpu, memory=self.memory
        )

    def check(self, task: "Task") -> bool:
        return all([
            self.cpu >= task.topology.cpu,
            self.memory >= task.topology.memory
        ])

    def __operate(self, task: "Task", op: Callable) -> None:
        self.cpu = op(self.cpu, task.topology.cpu)
        self.memory = op(self.memory, task.topology.memory)

    def take(self, task: "Task") -> None:
        self.__operate(task, operator.sub)

    def give(self, task: "Task") -> None:
        self.__operate(task, operator.add)


class Stateful(object):
    valid_states = [State.PENDING, State.FAILURE, State.SUCCESS, State.ERROR]


class Status(Stateful):
    def __init__(
        self, context: Text, description: Text,
        state: State, target_url: Text
    ) -> None:
        self.context = context
        self.description = description
        self.state = state
        self.target_url = target_url

    def __eq__(self, other) -> bool:
        return all((
           self.context == other.context,
           self.description == other.description,
           self.state == other.state,
           self.target_url == other.target_url
        ))

    @property
    def pending(self) -> bool:
        return self.state == State.PENDING

    @property
    def succeeded(self) -> bool:
        return self.state == State.SUCCESS

    @property
    def failed(self) -> bool:
        return self.state in [State.ERROR, State.FAILURE]

    @property
    def taken(self) -> bool:
        return "taken" in self.description.lower()

    @property
    def unassigned(self) -> bool:
        return "unassigned" in self.description.lower()

    @property
    def rerun_pending(self) -> bool:
        return self.description == RERUN_PENDING

    @property
    def processing(self) -> bool:
        return any((
            self.pending, self.rerun_pending, self.taken, self.unassigned
        ))

    def stalled(self, task: "Task") -> bool:
        """Checks if commit status is timed out"""
        now = datetime.now(pytz.UTC)
        timeout = timedelta(seconds=task.timeout)
        if not timeout:
            return False
        parsed = parse.parse(TASK_TAKEN_FMT, self.description)
        if not parsed:
            return False

        taken_on = parser.parse(parsed["date"])
        extra = timedelta(seconds=STALE_TASK_EXTRA_TIME)
        deadline = taken_on + timeout + extra
        if deadline > now:
            return False

        return True

    @staticmethod
    def from_dict(dict_data: Dict) -> "Status":
        """Fabric for Status"""
        return Status(
            context=dict_data["context"],
            description=dict_data["description"],
            state=State.from_str(dict_data["state"]),
            target_url=dict_data["targetUrl"]
        )


class Commit(object):
    """Represents the commit with GitHub's statuses"""
    def __init__(self, sha: Text, statuses_data: Dict) -> None:
        self.sha = sha
        self.statuses = {
            k: Status.from_dict(v) for k, v in statuses_data.items()
        }

    def __eq__(self, other) -> bool:
        return all((
            ss == os for ss, os in zip(self.statuses, other.statuses)
        )) and self.sha == other.sha

    @staticmethod
    def from_dict(data_dict: Dict) -> "Commit":
        """Fabric for Commit"""
        return Commit(
            sha=util.get_commit_sha(data_dict),
            statuses_data=util.get_statuses(data_dict)
        )


class PullRequest(object):
    """Represents the GitHub's pull request"""
    def __init__(
        self, pr_number: int, author: Text, base_ref: Text,
        mergeable: Text, labels: List[Text], commit_data: Dict
    ) -> None:
        self.number = pr_number
        self.author = author
        self.base_ref = base_ref
        self.labels = [Label.from_str(l) for l in labels]
        self.commit = Commit.from_dict(commit_data)
        self.mergeable = mergeable != "CONFLICTING"

    def __eq__(self, other) -> bool:
        return all((
            self.number == other.number,
            self.author == other.author,
            self.base_ref == other.base_ref,
            self.commit == other.commit,
            self.mergeable == other.mergeable
        )) and all((sl == ol for sl, ol in zip(self.labels, other.labels)))

    @property
    def acked(self) -> bool:
        return Label.ACK in self.labels

    @property
    def postponed(self) -> bool:
        return Label.POSTPONE in self.labels

    @property
    def needs_rerun(self) -> bool:
        return Label.RERUN in self.labels

    @property
    def needs_rebase(self) -> bool:
        return Label.REBASE in self.labels

    @property
    def prioritized(self) -> bool:
        return Label.PRIORITIZED in self.labels

    def __get_tasks_file_content(self, world: World) -> ByteString:
        """Gets the tasks file which belongs to this PR by HTTP"""
        tasks_file_url = (
            "https://raw.githubusercontent.com/{owner}/{repo}/{sha}/{path}"
        )
        res = world.session.get(
            url=tasks_file_url.format(
                owner=world.repo_owner,
                repo=world.repo_name,
                path=world.tasks_path,
                sha=self.commit.sha
            )
        )
        if res.status_code != 200:
            # If the file doesn't exist in the commit, we'll get in from the
            # base branch
            # Actually, this branch should never be executed...
            res = world.session.get(
                url=tasks_file_url.format(
                    owner=world.repo_owner,
                    repo=world.repo_name,
                    path=world.tasks_path,
                    sha=self.base_ref
                )
            )
        return res.content

    def get_tasks_data(self, world: World) -> Dict:
        """Loads the PR's tasks file into dictionary

        Raises:
            (yaml.error.YAMLError, TypeError, KeyError)

        Returns:
            dict: Dictionary of a tasks defined in the tasks file.
        """
        tasks_file_content = self.__get_tasks_file_content(world)
        return yaml.load(tasks_file_content)["jobs"]

    def __remove_label(self, world: World, label: Label) -> None:
        """Removes PR's label on GitHub using REST API

        Raises:
            github3.exceptions.NotFoundError
        """
        world.check_graphql_limit()

        world.github_api.pull_request(
            world.repo_owner, world.repo_name, self.number
        ).issue().remove_label(label.value)

    def __add_label(self, world: World, label: Label) -> None:
        """Adds PR's label on GitHub using REST API"""
        world.check_graphql_limit()

        world.github_api.pull_request(
            world.repo_owner, world.repo_name, self.number
        ).issue().add_labels(label.value)

    def remove_rerun_label(self, world: World) -> None:
        self.__remove_label(world, Label.RERUN)

    def remove_rebase_label(self, world: World) -> None:
        self.__remove_label(world, Label.REBASE)

    def remove_blacklist_label(self, world: World) -> None:
        self.__remove_label(world, Label.BLACKLIST)

    def add_rebase_label(self, world: World) -> None:
        self.__add_label(world, Label.REBASE)

    @staticmethod
    def from_dict(data_dict: Dict) -> "PullRequest":
        """Fabric for PullRequest"""
        return PullRequest(
            pr_number=data_dict["number"],
            author=data_dict["author"]["login"],
            base_ref=data_dict["baseRefName"],
            mergeable=data_dict["mergeable"],
            labels=util.get_labels(data_dict),
            commit_data=util.get_last_commit(data_dict)
        )


class Task(object):
    """Represents a task defined in a task file"""
    def __init__(
        self, name: Text, pr_number: int, commit_sha: Text, pr_author: Text,
        repo_url: Text, task_data: Dict, job_handler: Callable
    ) -> None:
        """Constructs the instance of a Task to be processed by the handler"""
        self.name = name
        self.pr_number = pr_number
        self.commit_sha = commit_sha
        self.repo_url = repo_url
        self.pr_author = pr_author
        self.ref_spec = "pull/{}/head".format(pr_number)

        # The data should be a dictionary with the following structure:

        # fedora-27/simple_replication:
        #   requires: [fedora-27/build]
        #   priority: 50
        #   job:
        #       class: RunPytest
        #       args:
        #           build_url: '{fedora-27/build_url}'
        #           test_suite: test_integration / test_simple_replication.py
        #           template: *ci-master-f27
        #           timeout: 3600
        #           topology: *master_1repl
        job_data = task_data["job"]
        job_data["args"]["task_name"] = self.name
        job_data["args"]["pr_number"] = self.pr_number
        job_data["args"]["pr_author"] = self.pr_author

        self.job = job_handler(
            job_data,
            {
                "git_repo": self.repo_url,
                "git_refspec": self.ref_spec
            }
        )

        self.dependencies = task_data["requires"]
        job_arguments_data = job_data["args"]
        self.timeout = job_arguments_data.get("timeout")
        topology_data = job_arguments_data.get("topology")
        if topology_data is None:
            self.topology = Topology()
        else:
            self.topology = Topology.from_dict(topology_data)
        self.description = ""

    def check_dependencies(self, statuses: Dict=None) -> bool:
        """Checks if the dependent tasks are done

        In our tasks definitions file we're having structure like this:

        fedora-27/simple_replication:
            requires: [fedora-27/build]

        So to run a task we need to make sure if the dependent task, like
        the fedora-27/build in the example above. And as all dependent tasks
        statuses in reality are commit statuses on GitHub, we need to check
        if all of them are succeeded.
        """
        if statuses is None:
            statuses = dict()

        def inner():
            for d in self.dependencies:
                status = statuses.get(d)
                if status is not None:
                    yield status.succeeded
                else:
                    yield False

        return all(inner())

    def lock(self, world: World) -> None:
        """Creates a commit status on GitHub using REST API

        Tries to lock a task through creation of a commit status on GitHub
        so the task could be later processed.
        """
        status = world.poll_status(self.pr_number, self.name)

        if status.failed or status.succeeded:
            raise EnvironmentError(
                "Task '{}' PR#{} was already processed.".format(
                    self.name, self.pr_number
                )
            )

        if status.pending and status.taken:
            raise EnvironmentError(
                "Task '{}' PR#{} is already locked.".format(
                    self.name, self.pr_number
                )
            )

        time_now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        description = TASK_TAKEN_FMT.format(
            runner_id=world.runner_id,
            date=time_now
        )
        world.create_status(self, State.PENDING, description)

        sleep(RACE_TIMEOUT)

        status = world.poll_status(self.pr_number, self.name)

        if status.description != description:
            raise EnvironmentError(
                "Task '{}' PR#{} changed. Unable to lock.".format(
                    self.name, self.pr_number
                )
            )

        self.description = description

    def set_unassigned(self, world: World) -> None:
        """Creates a commit status on GitHub using REST API

        Sets the status description to unassigned.
        """
        try:
            status = world.poll_status(self.pr_number, self.name)
        except EnvironmentError:
            world.create_status(self, State.PENDING, "unassigned")
            return

        if status.processing:
            raise EnvironmentError(
                "Already processing task {} PR#{}".format(
                    self.name, self.pr_number
                )
            )


    def set_rerun(self, world: World) -> None:
        """Creates a commit status on GitHub using REST API

        Sets the status description to RERUN_PENDING value.
        """
        status = world.poll_status(self.pr_number, self.name)
        if status.succeeded or (status.taken and not status.stalled):
            raise EnvironmentError(
                "Task {} PR#{} is changed".format(
                    self.name, self.pr_number
                )
            )
        if status.rerun_pending:
            raise EnvironmentError(
                "Task {} PR#{} is already updated for rerun".format(
                    self.name, self.pr_number
                )
            )

        world.create_status(self, State.PENDING, RERUN_PENDING)

    def execute(self, world: World, statuses: Dict) -> None:
        """Runs the related task class defined in tasks/tasks.py"""
        dependencies_results = {}
        for dep in self.dependencies:
            status = statuses.get(dep)
            if status is None:
                raise RuntimeError(
                    "Could not check dependencies for task {} PR#{}".format(
                        self.name, self.pr_number
                    )
                )
            dependencies_results[dep] = JobResult(
                status.state, status.description, status.target_url
            )

        result = self.job(world.repo_owner, dependencies_results)

        try:
            status = world.poll_status(self.pr_number, self.name)
        except EnvironmentError:
            raise ReferenceError(
                "Task {} PR#{} was updated".format(
                    self.name, self.pr_number
                )
            )

        if status.description != self.description:
            raise EnvironmentError(
                "Task {} PR#{} was processed by multiple runners".format(
                    self.name, self.pr_number
                )
            )
        world.create_status(self, result.state, result.description, result.url)


class ExitHandler(object):
    done = False
    aborted = False
    task = None

    def finish(self, signum, frame):
        if self.done:
            return self.abort(signum, frame)

        self.done = True

    def abort(self, signum, frame):
        if self.aborted:
            return self.quit()

        self.done = True
        self.aborted = True

    def quit(self):
        sys.exit()

    def register_task(self, task):
        self.task = task

    def unregister_task(self):
        self.task = None


class JobResult(Stateful):
    def __init__(
        self, state: State, description: Text="", url: Text=""
    ) -> None:
        if state not in self.valid_states:
            raise ValueError('invalid state: {}'.format(state))

        self.state = state
        self.description = description[:GITHUB_DESCRIPTION_LIMIT]
        self.url = url


class JobDispatcher(AbcCallable):
    def __init__(
        self, job_data: Dict, build_target: Dict[Text, Text]
    ) -> None:
        """Constructs a job for a runner from a given job dictionary

        The job dictionary should have the following structure:

        class: RunPytest
        args:
            build_url: '{fedora-27/build_url}'
            test_suite: path/to/test.py
            template: *ci-master-f27
            timeout: 3600
            topology:
                name: topology_name
                cpu: 4
                memory: 5750
        """
        self.task_class = getattr(tasks, job_data["class"])
        self.kwargs = job_data["args"]
        self.kwarg_lookup = build_target

    @property
    def timeout(self) -> int:
        return self.kwargs.get('timeout') or 0

    def __call__(
        self, repo_owner: Text, dependencies_results: Dict=None
    ) -> JobResult:
        """Calls the constructed job and waits for its result"""

        # As we can have dependencies, obviously, we will need theirs results
        # For example, URL with RPM packages
        if dependencies_results is not None:
            for task_name, result in dependencies_results.items():
                self.kwarg_lookup[
                    "{}_description".format(task_name)
                ] = result.description
                self.kwarg_lookup["{}_url".format(task_name)] = result.url

        kwargs = {}
        for key, value in self.kwargs.items():
            if isinstance(value, str):
                value = value.format(**self.kwarg_lookup)
            kwargs[key] = value

        job = self.task_class(repo_owner=repo_owner, **kwargs)
        try:
            job()
        except TaskException as e:
            description = str(e)
            state = State.ERROR
            sentry_report_exception({"module": "tasks"})
        else:
            description = job.description
            if job.returncode == 0:
                state = State.SUCCESS
            else:
                state = State.FAILURE

        return JobResult(state, description, job.remote_url)
