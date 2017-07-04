import logging
import os
import shutil
import urllib
import uuid

from .ansible import AnsiblePlaybook
from .common import (FallibleTask, TaskException, PopenTask,
                     logging_init_file_handler, create_file_from_template)
from . import constants
from .remote_storage import GzipLogFiles, FedoraPeopleUpload
from .vagrant import VagrantUp, VagrantProvision, VagrantCleanup


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
        self.remote_url = ''
        self.returncode = 1

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
        else:
            self.remote_url = urllib.parse.urljoin(
                constants.FEDORAPEOPLE_JOBS_URL, self.uuid)
            logging.info('Job published at: {remote_url}'.format(
                remote_url=self.remote_url))

    def terminate(self):
        logging.critical(
            "Terminating execution, runtime exceeded {seconds}s".format(
                seconds=self.timeout))

        # Common cause of job timeout: out of disk space
        stat = os.statvfs(self.data_dir)
        if stat.f_bavail == 0:
            logging.critical('No free disk space')

        super(JobTask, self).terminate()


class Build(JobTask):
    action_name = 'build'

    def __init__(self, git_refspec=None, git_version=None, git_repo=None,
                 publish_artifacts=True, timeout=constants.BUILD_TIMEOUT,
                 **kwargs):
        super(Build, self).__init__(timeout=timeout, **kwargs)
        self.git_refspec = git_refspec
        self.git_version = git_version
        self.git_repo = git_repo
        self.publish_artifacts = publish_artifacts

    @with_vagrant
    def _run(self):
        try:
            self.build()
            logging.info('>>>>>> BUILD PASSED <<<<<<')
            self.returncode = 0
        except TaskException:
            logging.error('>>>>>> BUILD FAILED <<<<<<')
            self.returncode = 1
        finally:
            self.collect_build_artifacts()
            self.compress_logs()
            if self.publish_artifacts:
                try:
                    self.create_yum_repo()
                except TaskException:
                    logging.error('Failed to create repo')
                    self.returncode = 1
                finally:
                    self.upload_artifacts()

    def build(self):
        self.execute_subtask(
            AnsiblePlaybook(
                playbook=constants.ANSIBLE_PLAYBOOK_BUILD,
                extra_vars={
                    'git_refspec': self.git_refspec,
                    'git_version': self.git_version,
                    'git_repo': self.git_repo},
                timeout=None))

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
                dict(job_url=urllib.parse.urljoin(base_url, self.uuid)))
        except (OSError, IOError) as exc:
            msg = 'Failed to create repo file'
            logging.debug(exc)
            logging.error(msg)
            raise TaskException(self, msg)


class RunTests(JobTask):
    action_name = 'run_tests'

    def __init__(self, build_url, test_suite, publish_artifacts=True,
                 timeout=constants.RUN_TESTS_TIMEOUT, **kwargs):
        super(RunTests, self).__init__(timeout=timeout, **kwargs)
        self.build_url = build_url + '/'
        self.test_suite = test_suite
        self.publish_artifacts = publish_artifacts

    def _before(self):
        super(RunTests, self)._before()

        # Prepare test config files
        try:
            create_file_from_template(
                constants.ANSIBLE_VARS_TEMPLATE.format(
                    action_name=self.action_name),
                os.path.join(self.data_dir, 'vars.yml'),
                dict(repofile_url=urllib.parse.urljoin(
                        self.build_url, 'rpms/freeipa-prci.repo')))
        except (OSError, IOError) as exc:
            msg = "Failed to prepare test config files"
            logging.debug(exc, exc_info=True)
            logging.critical(msg)
            raise exc

    @with_vagrant
    def _run(self):
        try:
            self.run_tests()
            logging.info('>>>>> TESTS PASSED <<<<<<')
            self.returncode = 0
        except TaskException as exc:
            self.returncode = exc.task.returncode
            if self.returncode == 1:
                logging.error('>>>>>> TESTS FAILED <<<<<<')
            else:
                logging.error('>>>>>> PYTEST ERROR ({code}) <<<<<<'.format(
                    code=self.returncode))
        finally:
            self.compress_logs()
            if self.publish_artifacts:
                self.upload_artifacts()

    def run_tests(self):
        self.execute_subtask(
            PopenTask(['vagrant', 'ssh', '-c', (
                'IPATEST_YAML_CONFIG=/vagrant/ipa-test-config.yaml '
                'ipa-run-tests {test_suite} '
                '--verbose --logging-level=debug --logfile-dir=/vagrant/ '
                '--junit-xml=/vagrant/results.xml'
                ).format(test_suite=self.test_suite)]))
