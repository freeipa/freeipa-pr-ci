import os
import urllib

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')
JOBS_DIR = os.path.join(BASE_DIR, 'jobs')

CLOUD_BUCKET = 'freeipa-org-pr-ci'
CLOUD_DIR = 's3://freeipa-org-pr-ci/'
CLOUD_URL = 'http://freeipa-org-pr-ci.s3-website.eu-central-1.amazonaws.com/'
CLOUD_JOBS_DIR = 'jobs/'
CLOUD_JOBS_URL = urllib.parse.urljoin(CLOUD_URL, CLOUD_JOBS_DIR)

TASKS_DIR = os.path.join(BASE_DIR, 'tasks')

BUILD_PASSED_DESCRIPTION = "\(^_^)/"
BUILD_FAILED_DESCRIPTION = "(✖╭╮✖)"

UUID_RE = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'

RUNNER_LOG = 'runner.log'
FREEIPA_PRCI_REPOFILE = 'freeipa-prci.repo'
ANSIBLE_VARS_TEMPLATE = '{action_name}.vars.yml'
VAGRANTFILE_TEMPLATE = os.path.join('vagrantfiles', 'Vagrantfile.{vagrantfile_name}')
VAGRANT_IMAGE_PATH = '/root/.vagrant.d/boxes/{name}/{version}/{provider}/box.img'
LIBVIRT_IMAGE_PATH = '/var/lib/libvirt/images/{libvirt_name}_{version}.img'

ANSIBLE_CFG_FILE = os.path.join(TEMPLATES_DIR, 'ansible.cfg')

POPEN_TERM_TIMEOUT = 10
BUILD_TIMEOUT = 30*60
RUN_PYTEST_TIMEOUT = 90*60

# Topologies
DEFAULT_TOPOLOGY = 'master_1repl'

# Playbooks
ANSIBLE_PLAYBOOK_DIR = os.path.join(BASE_DIR, 'ansible')
ANSIBLE_PLAYBOOK_BUILD = os.path.join(ANSIBLE_PLAYBOOK_DIR, 'build.yml')
ANSIBLE_PLAYBOOK_COLLECT_BUILD = os.path.join(ANSIBLE_PLAYBOOK_DIR,
                                              'collect_build.yml')
