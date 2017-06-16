import os

BASE_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..')
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
JOB_DIR = os.path.join(BASE_DIR, 'jobs')


FEDORAPEOPLE_KEY_PATH = '/root/.ssh/freeipa_pr_ci'
FEDORAPEOPLE_DIR = 'ipa-maint@fedorapeople.org:/srv/groups/freeipa/prci/{path}'
FEDORAPEOPLE_BASE_URL = 'https://fedorapeople.org/groups/freeipa/prci/'

BUILD_RE = '\d{14}\+git[0-9a-f]{7}'

RUNNER_LOG = 'runner.log'
FREEIPA_PRCI_REPOFILE = 'freeipa-prci.repo'
CURRENT_SYMLINK = 'current'
BUILD_ID_FILE = 'build_id.json'

DATA_DIR = os.path.join(CURRENT_SYMLINK, '{action_name}')


# Playbooks
ANSIBLE_PLAYBOOK_DIR = os.path.join(BASE_DIR, 'ansible')
ANSIBLE_PLAYBOOK_BUILD = os.path.join(ANSIBLE_PLAYBOOK_DIR, 'build.yml')
ANSIBLE_PLAYBOOK_COLLECT_BUILD = os.path.join(ANSIBLE_PLAYBOOK_DIR,
                                              'collect_build.yml')


VAGRANTFILE_FILENAME = 'Vagrantfile.{action_name}'
ANSIBLE_INVENTORY_FILENAME = 'hosts.{action_name}'
