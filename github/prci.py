#!/usr/bin/python3

import argparse
import logging
import logging.config
import signal
import sys
from functools import partial
from time import sleep
from typing import Dict, Iterator, Optional, Text

import github3
import yaml
from github3.exceptions import NotFoundError

from internals.entities import (
    ExitHandler, JobDispatcher, PullRequest, Status, Task, World,
    sentry_report_exception
)
from internals.gql import util, queries


logger = logging.getLogger(__name__)


ERROR_BACKOFF_TIME = 600


def skipping_pr(reason: Text, number: int) -> None:
    logger.info("Skipping PR#%s: %s", number, reason)


def skipping_task(reason: Text, task: Task) -> None:
    logger.info(
        "Skipping %s of #%s: %s", task.name, task.pr_number, reason
    )


def create_parser():
    def config_file(path):
        def load_yaml(yml_path):
            try:
                with open(yml_path) as yml_file:
                    return yaml.load(yml_file)
            except IOError as e:
                raise argparse.ArgumentTypeError(
                    'Failed to open {}: {}'.format(yml_path, e))
            except yaml.YAMLError as e:
                raise argparse.ArgumentTypeError(
                    'Failed to parse YAML from {}: {}'.format(yml_path, e))

        config = load_yaml(path)
        try:
            config['credentials']
            config['repository']
            config['tasks_file']
            config['logging']
        except KeyError as exc:
            raise argparse.ArgumentTypeError(
                'Missing required section {} in configuration.', exc)

        try:
            whitelist_file = config.pop('whitelist_file')
        except KeyError:
            logger.warning('No whitelist file supplied. Manual approval will '
                           'be needed for all PRs.')
            config['whitelist'] = []
        else:
            config['whitelist'] = load_yaml(whitelist_file)

        return config

    parser = argparse.ArgumentParser()
    parser.add_argument(
        'ID', type=str,
        help='Unique runner ID',
    )
    parser.add_argument(
        '--config', type=config_file, required=True,
        help='YAML file with complete configuration.',
    )

    return parser


def process_pull_request(
    world: World, pull_request: PullRequest, repository_url: Text
) -> Optional[Iterator[Task]]:

    if pull_request.postponed:
        skipping_pr("postponed", pull_request.number)
        return None

    if not pull_request.mergeable:
        skipping_pr("can't be merged", pull_request.number)
        if not pull_request.needs_rebase:
            pull_request.add_rebase_label(world)
        return None

    try:
        tasks_data = pull_request.get_tasks_data(world)
    except (yaml.error.YAMLError, TypeError, KeyError) as e:
        logger.error(e)
        return None

    if pull_request.needs_rerun:
        # If all statuses are not failed (not in state ERROR or FAILURE) and
        # re-run label was set previously, remove the re-run label
        if all(map(
            lambda t: t in pull_request.commit.statuses
            and not pull_request.commit.statuses[t].failed,
            tasks_data.keys()
        )):
            try:
                pull_request.remove_rerun_label(world)
            except NotFoundError as e:
                logger.warning(e)

    for name, task_data in tasks_data.items():
        task = Task(
            name, pull_request.number, pull_request.commit.sha,
            pull_request.author, repository_url, task_data, JobDispatcher
        )
        if task.name not in pull_request.commit.statuses:
            if (
                pull_request.author in world.whitelist
                or pull_request.needs_rerun
            ):
                logger.info(
                    "PR#%s %s updating status to unassigned",
                    pull_request.number, task.name
                )
                try:
                    task.set_unassigned(world)
                except EnvironmentError as e:
                    logger.error(e)
                continue

        status = pull_request.commit.statuses.get(task.name)
        if status is not None:
            task = process_status(
                world, status, task, pull_request.needs_rerun
            )
            if task is None:
                continue

        task = process_task(world, task, pull_request.commit.statuses)
        if task is None:
            continue

        yield task


def process_status(
    world: World, status: Status, task: Task, needs_rerun: bool=False
) -> Optional[Task]:
    """Checks for status related skipping conditions"""
    if status.unassigned or status.rerun_pending:
        return task

    if needs_rerun:
        if status.failed:
            logger.info(
                "Setting pending %s PR #%s",
                task.name, task.pr_number
            )
            try:
                task.set_rerun(world)
            except EnvironmentError as e:
                logger.warning(e)

    if status.stalled(task):
        logger.info(
            "Task %s on PR #%s is stale. Updating for rerun.",
            task.name, task.pr_number
        )
        try:
            task.set_rerun(world)
        except EnvironmentError as e:
            logger.warning(e)


def process_task(
    world: World, task: Task, statuses: Dict
) -> Optional[Task]:
    """Checks for task related skipping conditions"""

    # If there's no task name in GitHub commit statuses, we should skip it
    # It happens in a case when PR's author is not listed in whitelist
    # and statuses creation was not triggered by adding a re-run label by
    # someone from whitelist
    if statuses.get(task.name) is None:
        skipping_task("GitHub status doesn't exist", task)
        return None

    if not world.available_resources.check(task):
        skipping_task("not enough resources", task)
        return None

    if not task.check_dependencies(statuses):
        skipping_task("waiting for dependencies", task)
        return None

    logger.info(
        "Attempting to lock a task %s for PR#%s.",
        task.name, task.pr_number
    )
    try:
        task.lock(world)
    except EnvironmentError as e:
        logger.warning(e)
        return None

    logger.info(
        "%s PR#%s is successfully locked.",
        task.name, task.pr_number
    )

    return task


def main():
    parser = create_parser()
    args = parser.parse_args()

    runner_id = args.ID
    config = args.config

    credentials = config["credentials"]
    repo = config["repository"]
    tasks_path = config["tasks_file"]
    whitelist = config["whitelist"]
    no_task_backoff_time = config["no_task_backoff_time"]

    logging.config.dictConfig(config["logging"])

    exit_handler = ExitHandler()
    signal.signal(signal.SIGINT, exit_handler.finish)
    signal.signal(signal.SIGTERM, exit_handler.abort)

    gh = github3.login(token=credentials["token"])
    session = util.create_session(util.make_headers(credentials["token"]))
    do_request = partial(util.perform_request, session=session)

    world = World(
        graphql_request=do_request,
        github_api=gh,
        session=session,
        repo_owner=repo["owner"],
        repo_name=repo["name"],
        runner_id=runner_id,
        tasks_path=tasks_path,
        whitelist=whitelist
    )

    while not exit_handler.done:
        world.check_graphql_limit()

        try:
            response = do_request(
                query=queries.make_pull_requests_query(
                    world.repo_owner, world.repo_name
                )
            )
        except EnvironmentError as e:
            logger.error(e)
            sys.exit(1)

        data = util.get_data(response)
        repo = util.get_repository(data)
        repo_url = util.get_repository_url(repo)
        pull_requests_data = util.get_pull_requests(repo)

        pull_requests = sorted(
            (
                PullRequest.from_dict(pr_data)
                for pr_data in pull_requests_data
            ),
            key=lambda pr: not pr.prioritized
        )
        for pull_request in pull_requests:
            for task in process_pull_request(world, pull_request, repo_url):
                exit_handler.register_task(task)
                world.available_resources.take(task)
                logger.info(
                    "Available resources: %s", world.available_resources
                )
                try:
                    task.execute(world, pull_request.commit.statuses)
                except ReferenceError as e:
                    logger.warning(e)
                except (EnvironmentError, RuntimeError) as e:
                    logger.error(e)
                    sentry_report_exception({"module": "github"})
                    sleep(ERROR_BACKOFF_TIME)
                finally:
                    exit_handler.unregister_task()
                    world.available_resources.give(task)
                    logger.info(
                        "Available resources: %s", world.available_resources
                    )

        sleep(no_task_backoff_time)


if __name__ == "__main__":
    main()
