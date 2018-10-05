import logging
import os
import shutil
import socket
import urllib
import uuid

from .ansible import AnsiblePlaybook
from .common import (FallibleTask, TaskException, PopenTask,
                     logging_init_file_handler, create_file_from_template)
from . import constants
from .remote_storage import GzipLogFiles, CloudUpload, CreateRootIndex
from .vagrant import with_vagrant


class JobTask(FallibleTask):
    def __init__(self, template, no_destroy=False, publish_artifacts=True,
                 link_image=True, pr_number=None, pr_author=None,
                 task_name=None, repo_owner=None, **kwargs):
        super(JobTask, self).__init__(**kwargs)
        self.template_name = template['name']
        self.template_version = template['version']
        self.publish_artifacts = publish_artifacts
        self.timeout = kwargs.get('timeout', None)
        self.uuid = str(uuid.uuid1())
        self.remote_url = ''
        self.returncode = 1
        self.no_destroy = no_destroy
        self.description = '<no description>'
        self.link_image = link_image
        self.pr_number = pr_number
        self.pr_author = pr_author
        self.task_name = task_name
        self.repo_owner = repo_owner

    @property
    def vagrantfile(self):
        return constants.VAGRANTFILE_TEMPLATE.format(
            vagrantfile_name=self.action_name)

    @property
    def data_dir(self):
        return os.path.join(constants.JOBS_DIR, self.uuid)

    def compress_logs(self):
        self.execute_subtask(
            GzipLogFiles(self.data_dir, raise_on_err=False))

    def write_hostname_to_file(self):
        try:
            hostname = socket.gethostname()
            hostname = hostname.split('.')[0]  # make sure we don't leak fqdn
            with open('hostname', 'w') as hostname_f:
                hostname_f.write(hostname)
        except Exception as exc:
            logging.warning("Failed to write hostname to file")
            logging.debug(exc, exc_info=True)

    def _before(self):
        # Create job dir
        try:
            os.makedirs(self.data_dir)
        except (OSError, IOError) as exc:
            msg = "Failed to create job directory"
            logging.critical(msg)
            logging.debug(exc, exc_info=True)
            raise TaskException(self, msg)

        # Change working dir and initialize logging
        os.chdir(self.data_dir)
        logging_init_file_handler()

        logging.info("Initializing job {uuid}".format(uuid=self.uuid))

        # Create a hostname file for debugging purposes
        self.write_hostname_to_file()

        # Prepare files for vagrant
        try:
            shutil.copy(constants.ANSIBLE_CFG_FILE, self.data_dir)
            create_file_from_template(
                self.vagrantfile,
                os.path.join(self.data_dir, 'Vagrantfile'),
                dict(vagrant_template_name=self.template_name,
                     vagrant_template_version=self.template_version))
        except (OSError, IOError) as exc:
            msg = "Failed to prepare job"
            logging.critical(msg)
            logging.debug(exc, exc_info=True)
            raise TaskException(self, msg)

    def _after(self):
        self.compress_logs()
        if self.publish_artifacts:
            self.upload_artifacts()
            # list only "freeipa" repo PRs in root index
            # (Jobs of PRs against forks are not listed)
            if self.repo_owner == 'freeipa':
                self.create_root_index()

    def upload_artifacts(self):
        try:
            self.execute_subtask(
                CloudUpload(uuid=self.uuid,
                            repo_owner=self.repo_owner,
                            pr_number=self.pr_number,
                            pr_author=self.pr_author,
                            task_name=self.task_name,
                            returncode=self.returncode,
                            timeout=5*60))
        except Exception as exc:
            logging.debug(exc, exc_info=True)
            raise TaskException(self, "Failed to publish artifacts")
        else:
            self.remote_url = urllib.parse.urljoin(
                constants.CLOUD_JOBS_URL, self.uuid)
            logging.info('Job published at: {remote_url}'.format(
                remote_url=self.remote_url))

    def create_root_index(self):
        """
        Create jobs root index
        """
        try:
            self.execute_subtask(
                CreateRootIndex(uuid=self.uuid,
                                repo_owner=self.repo_owner,
                                pr_number=self.pr_number,
                                pr_author=self.pr_author,
                                task_name=self.task_name,
                                returncode=self.returncode,
                                timeout=30))
        except Exception as exc:
            logging.error('Failed to create jobs root index. This should not '
                          'affect base PRCI functionality')
            logging.debug(exc, exc_info=True)


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

    def __init__(self, template, git_refspec=None, git_version=None, git_repo=None,
                 timeout=constants.BUILD_TIMEOUT, topology=None, **kwargs):
        super(Build, self).__init__(template, timeout=timeout, **kwargs)
        self.git_refspec = git_refspec
        self.git_version = git_version
        self.git_repo = git_repo

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

    def _after(self):
        self.compress_logs()
        if self.publish_artifacts:
            try:
                self.create_yum_repo()
            except TaskException:
                logging.error('Failed to create repo')
                self.returncode = 1
            finally:
                self.upload_artifacts()
                # list only "freeipa" repo PRs in root index
                # (Jobs of PRs against forks are not listed)
                if self.repo_owner == 'freeipa':
                    self.create_root_index()

        if self.returncode == 0:
            self.description = constants.BUILD_PASSED_DESCRIPTION
        else:
            self.description = constants.BUILD_FAILED_DESCRIPTION

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

    def create_yum_repo(self, base_url=constants.CLOUD_JOBS_URL):
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
            logging.debug(exc, exc_info=True)
            logging.error(msg)
            raise TaskException(self, msg)


class RunPytest(JobTask):
    action_name = 'run_pytest'
    run_tests_cmd = 'ipa-run-tests'

    def __init__(self, template, build_url, test_suite, topology=None,
                 timeout=constants.RUN_PYTEST_TIMEOUT, update_packages=False,
                 xmlrpc=False, **kwargs):
        super(RunPytest, self).__init__(template, timeout=timeout, **kwargs)
        self.build_url = build_url + '/'
        self.test_suite = test_suite
        self.update_packages = update_packages
        self.xmlrpc = xmlrpc

        if not topology:
            topology = {'name': constants.DEFAULT_TOPOLOGY}

        self.topology_name = topology['name']

    @property
    def vagrantfile(self):
        return constants.VAGRANTFILE_TEMPLATE.format(
            vagrantfile_name=self.topology_name)

    def _before(self):
        super(RunPytest, self)._before()

        # Prepare test config files
        try:
            create_file_from_template(
                constants.ANSIBLE_VARS_TEMPLATE.format(
                    action_name=self.action_name),
                os.path.join(self.data_dir, 'vars.yml'),
                dict(repofile_url=urllib.parse.urljoin(
                        self.build_url, 'rpms/freeipa-prci.repo'),
                     update_packages=self.update_packages))
        except (OSError, IOError) as exc:
            msg = "Failed to prepare test config files"
            logging.debug(exc, exc_info=True)
            logging.critical(msg)
            raise exc

    @with_vagrant
    def _run(self):
        try:
            self.execute_tests()
            logging.info('>>>>> TESTS PASSED <<<<<<')
            self.returncode = 0
        except TaskException as exc:
            self.returncode = exc.task.returncode
            self._handle_test_exception(exc)

    def execute_tests(self):
        if self.xmlrpc:
            self.execute_subtask(
                PopenTask(
                    ['vagrant', 'ssh', '-c', "echo Secret.123 | kinit admin"],
                    timeout=None))
        self.execute_subtask(
            PopenTask(['vagrant', 'ssh', '-c', (
                'IPATEST_YAML_CONFIG=/vagrant/ipa-test-config.yaml '
                '{run_tests_cmd} {test_suite} '
                '--verbose --logging-level=debug --logfile-dir=/vagrant/ '
                '--html=/vagrant/report.html '
                '--junit-xml=/vagrant/junit.xml'
                ).format(
                    run_tests_cmd=self.run_tests_cmd,
                    test_suite=self.test_suite)],
                timeout=None))

    def _handle_test_exception(self, exc):
        if self.returncode == 1:
            logging.error('>>>>>> TESTS FAILED <<<<<<')
        else:
            logging.error('>>>>>> PYTEST ERROR ({code}) <<<<<<'.format(
                code=self.returncode))


class RunPytest2(RunPytest):
    run_tests_cmd = 'ipa-run-tests-2'


class RunPytest3(RunPytest):
    run_tests_cmd = 'ipa-run-tests-3'


class RunWebuiTests(RunPytest):
    action_name = 'webui'

    @property
    def vagrantfile(self):
        return constants.VAGRANTFILE_TEMPLATE.format(
            vagrantfile_name='ipaserver')

    def execute_tests(self):
        self.execute_subtask(
            PopenTask(['vagrant', 'ssh', '-c', (
                'ipa-run-webui-tests '
                '--verbose --logging-level=debug --logfile-dir=/vagrant/ '
                '--html=/vagrant/report.html '
                '--junit-xml=/vagrant/junit.xml '
                '{test_suite}'
                ).format(test_suite=self.test_suite)],
                timeout=None))

    def _handle_test_exception(self, exc):
        logging.error(
            '>>>>>> WEBUI TESTS FAILED (error code: {code}) <<<<<<'.format(
                code=self.returncode))
