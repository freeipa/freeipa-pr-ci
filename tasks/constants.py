import os
import urlparse

BASE_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..')
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')
TOPOLOGIES_DIR = os.path.join(BASE_DIR, 'topologies')
JOBS_DIR = os.path.join(BASE_DIR, 'jobs')

FEDORAPEOPLE_KEY_PATH = '/root/.ssh/freeipa_pr_ci'
FEDORAPEOPLE_DIR = 'ipa-maint@fedorapeople.org:/srv/groups/freeipa/prci/{path}'
FEDORAPEOPLE_BASE_URL = 'https://fedorapeople.org/groups/freeipa/prci/'
FEDORAPEOPLE_JOBS_URL = urlparse.urljoin(FEDORAPEOPLE_BASE_URL, 'jobs/')

UUID_RE = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'

RUNNER_LOG = 'runner.log'
FREEIPA_PRCI_REPOFILE = 'freeipa-prci.repo'

ANSIBLE_CFG_FILE = os.path.join(os.path.join(TEMPLATES_DIR, 'ansible.cfg'))
VAGRANTFILE_FILE = os.path.join(os.path.join(TOPOLOGIES_DIR,
    'Vagrantfile.{action_name}'))

# Playbooks
ANSIBLE_PLAYBOOK_DIR = os.path.join(BASE_DIR, 'ansible')
ANSIBLE_PLAYBOOK_BUILD = os.path.join(ANSIBLE_PLAYBOOK_DIR, 'build.yml')
ANSIBLE_PLAYBOOK_COLLECT_BUILD = os.path.join(ANSIBLE_PLAYBOOK_DIR,
                                              'collect_build.yml')
