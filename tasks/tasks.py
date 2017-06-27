from abc import abstractmethod
import logging
import json
import os
import shutil
import urlparse
import uuid

from ansible import AnsiblePlaybook
from common import (FallibleTask, TaskException, LOG_FILE_HANDLER,
                    PopenTask, logging_init_file_handler,
                    logging_init_stream_handler, create_file_from_template)
import constants
from remote_storage import GzipLogFiles, FedoraPeopleUpload
from vagrant import VagrantUp, VagrantProvision, VagrantCleanup


def with_vagrant(func):
    def wrapper(self, *args, **kwargs):
        try:
            self.execute_subtask(
                VagrantUp(timeout=None))
            self.execute_subtask(
                VagrantProvision(timeout=None))
        except TaskException as exc:
            logging.critical('vagrant or provisioning failed')
            raise exc
        else:
            func(self, *args, **kwargs)
        finally:
            self.execute_subtask(
                VagrantCleanup(raise_on_err=False))

    return wrapper


class JobTask(FallibleTask):
    def __init__(self, **kwargs):
        super(JobTask, self).__init__(**kwargs)
        self.timeout = kwargs.get('timeout', None)
        self.uuid = str(uuid.uuid1())

    @property
    def data_dir(self):
        return os.path.join(constants.JOBS_DIR, self.uuid)

    def compress_logs(self):
        self.execute_subtask(
            GzipLogFiles(self.data_dir, raise_on_err=False))

    def _before(self):
        # Create job dir
        try:
            os.makedirs(self.data_dir)
        except (OSError, IOError) as exc:
            msg = "Failed to create job directory"
            logging.critical(msg)
            logging.debug(exc)
            raise TaskException(self, msg)

        # Change working dir and initialize logging
        os.chdir(self.data_dir)
        logging_init_file_handler()

        logging.info("Initializing job {uuid}".format(uuid=self.uuid))
        
        # Prepare files for vagrant
        try:
            shutil.copy(constants.ANSIBLE_CFG_FILE, self.data_dir)
            shutil.copy(constants.VAGRANTFILE_FILE.format(
                action_name=self.action_name),
                os.path.join(self.data_dir, 'Vagrantfile'))
        except (OSError, IOError) as exc:
            msg = "Failed to prepare job"
            logging.critical(msg)
            logging.debug(exc)
            raise TaskException(self, msg)

    def upload_artifacts(self):
        try:
            self.execute_subtask(
                FedoraPeopleUpload(uuid=self.uuid, timeout=5*60))
        except Exception as exc:
            logging.debug(exc)
            raise TaskException(self, "Failed to publish artifacts")


class Build(JobTask):
    action_name = 'build'

    def __init__(self, git_refspec, publish_artifacts=True, **kwargs):
        super(Build, self).__init__(**kwargs)
        self.git_refspec = git_refspec
        self.publish_artifacts = publish_artifacts

    @with_vagrant
    def _run(self):
        try:
            self.build()
            logging.info('Build passed')
        except TaskException:
            logging.error('Build failed')
            raise
        finally:
            self.collect_build_artifacts()
            self.compress_logs()
            if self.publish_artifacts:
                try:
                    self.create_yum_repo()
                finally:
                    self.upload_artifacts()

    def build(self):
        self.execute_subtask(
            AnsiblePlaybook(
                playbook=constants.ANSIBLE_PLAYBOOK_BUILD,
                extra_vars={'git_refspec': self.git_refspec},
                timeout=20*60))

    def collect_build_artifacts(self):
        self.execute_subtask(
            AnsiblePlaybook(
                playbook=constants.ANSIBLE_PLAYBOOK_COLLECT_BUILD,
                raise_on_err=False))

    def create_yum_repo(self, base_url=constants.FEDORAPEOPLE_JOBS_URL):
        repo_path = os.path.join(self.data_dir, 'rpms')
        self.execute_subtask(
            PopenTask(['createrepo', repo_path]))
        try:
            create_file_from_template(
                constants.FREEIPA_PRCI_REPOFILE,
                os.path.join(repo_path, constants.FREEIPA_PRCI_REPOFILE),
                dict(job_url=urlparse.urljoin(base_url, self.uuid)))
        except (OSError, IOError) as exc:
            msg = 'Failed to create repo file'
            logging.debug(exc)
            logging.error(msg)
            raise TaskException(self, msg)


if __name__ == '__main__':
    logging_init_stream_handler()
    Build('pull/4/head')()
