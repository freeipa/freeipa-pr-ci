from abc import abstractmethod
import logging
import json
import os
import shutil
import urlparse

from ansible import AnsiblePlaybook
from common import (FallibleTask, TaskException, LOG_FILE_HANDLER,
                    PopenTask, init_logging, create_file_from_template)
import constants
from remote_storage import GzipLogFiles, FedoraPeopleUpload
from vagrant import VagrantUp, VagrantCleanup


def with_vagrant(func):
    def wrapper(self, *args, **kwargs):
        try:
            self.execute_subtask(
                VagrantUp(vagrantfile=self.vagrantfile, timeout=None))
        except TaskException as exc:
            logging.critical('vagrant up failed')
            raise exc
        else:
            func(self, *args, **kwargs)
        finally:
            self.execute_subtask(
                VagrantCleanup(vagrantfile=self.vagrantfile,
                               raise_on_err=False))

    return wrapper


def create_current_symlink_from_build_id(build_id):
    try:
        os.symlink(build_id, constants.CURRENT_SYMLINK)
    except (OSError, IOError) as exc:
        msg = 'Failed to create "current" symlink'
        logging.debug(exc)
        logging.critical(msg)
        raise TaskException(msg)


class JobTask(FallibleTask):
    def __init__(self, **kwargs):
        super(JobTask, self).__init__(**kwargs)
        self.timeout = kwargs.get('timeout', None)

    @property
    def vagrantfile(self):
        return constants.VAGRANTFILE_FILENAME.format(
            action_name=self.action_name)

    @property
    def ansible_inventory(self):
        return constants.ANSIBLE_INVENTORY_FILENAME.format(
            action_name=self.action_name)

    @property
    def data_dir(self):
        return constants.DATA_DIR.format(
            action_name=self.action_name)

    @abstractmethod
    def create_current_symlink(self):
        pass

    def prepare(self):
        try:
            os.remove(constants.CURRENT_SYMLINK)
        except (IOError, OSError):
            pass
        # Make sure symlink was deleted
        if os.path.exists(constants.CURRENT_SYMLINK):
            msg = 'Failed to remove "current" symlink'
            logging.critical(msg)
            raise TaskException(self, msg)

    def collect_runner_log(self):
        if LOG_FILE_HANDLER is not None:
            LOG_FILE_HANDLER.flush()
        try:
            shutil.copy(constants.RUNNER_LOG, os.path.join(self.data_dir, ''))
        except (shutil.Error, IOError, OSError):
            logging.warning('Failed to copy runner log')

    def compress_logs(self):
        self.execute_subtask(
            GzipLogFiles(self.data_dir, raise_on_err=False))

    def upload_artifacts(self):
        try:
            try:
                src = os.readlink(constants.CURRENT_SYMLINK)
            except (OSError, IOError):
                logging.critical('Failed to read target of "current" symlink')
                raise
            self.execute_subtask(
                FedoraPeopleUpload(src=src, timeout=5*60))
        except Exception:
            raise TaskException(self, "Failed to publish artifacts")


class Build(JobTask):
    action_name = 'build'

    def __init__(self, git_refspec, publish_artifacts=True, **kwargs):
        super(Build, self).__init__(**kwargs)
        self.git_refspec = git_refspec
        self.publish_artifacts = publish_artifacts
        self.build_id = None

    @with_vagrant
    def _run(self):
        try:
            self.prepare()
            self.build()
            self.create_current_symlink()
            logging.info('Build passed')
        except TaskException:
            logging.error('Build failed')
            raise
        finally:
            self.collect_build_artifacts()
            self.collect_runner_log()
            self.compress_logs()
            if self.publish_artifacts:
                try:
                    self.create_yum_repo()
                finally:
                    self.upload_artifacts()

    def create_current_symlink(self):
        try:
            path = constants.BUILD_ID_FILE
            try:
                with open(path) as json_data:
                    data = json.load(json_data)
            except (IOError, OSError):
                logging.critical(
                    'Failed to read build_id from "{path}"'.format(
                        path=path))
                raise
            self.build_id = data['build_id']
            create_current_symlink_from_build_id(self.build_id)
        except Exception:
            raise TaskException(self, 'Failed to create "current" symlink')

    def build(self):
        self.execute_subtask(
            AnsiblePlaybook(
                playbook=constants.ANSIBLE_PLAYBOOK_BUILD,
                extra_vars={'git_refspec': self.git_refspec},
                inventory=self.ansible_inventory,
                timeout=20*60))

    def collect_build_artifacts(self):
        self.execute_subtask(
            AnsiblePlaybook(
                playbook=constants.ANSIBLE_PLAYBOOK_COLLECT_BUILD,
                inventory=self.ansible_inventory,
                raise_on_err=False))

    def create_yum_repo(self, base_url=constants.FEDORAPEOPLE_BASE_URL):
        repo_path = os.path.join(self.data_dir, 'rpms')
        self.execute_subtask(
            PopenTask(['createrepo', repo_path]))
        try:
            create_file_from_template(
                constants.FREEIPA_PRCI_REPOFILE,
                os.path.join(repo_path, constants.FREEIPA_PRCI_REPOFILE),
                dict(build_url=urlparse.urljoin(base_url, self.build_id)))
        except (OSError, IOError) as exc:
            msg = 'Failed to create repo file'
            logging.debug(exc)
            logging.error(msg)
            raise TaskException(self, msg)


if __name__ == '__main__':
    init_logging()
    Build('pull/4/head')()
