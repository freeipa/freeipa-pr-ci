import os


RUNNER_LOG = 'runner.log'
CURRENT_SYMLINK = 'current'
BUILD_ID_FILE = 'build_id.json'

DATA_DIR = os.path.join(CURRENT_SYMLINK, '{action_name}')


# Playbooks
ANSIBLE_PLAYBOOK_DIR = '../ansible'
ANSIBLE_PLAYBOOK_BUILD = os.path.join(ANSIBLE_PLAYBOOK_DIR, 'build.yml')
ANSIBLE_PLAYBOOK_COLLECT_BUILD = os.path.join(ANSIBLE_PLAYBOOK_DIR,
                                              'collect_build.yml')


VAGRANTFILE_FILENAME = 'Vagrantfile.{action_name}'
ANSIBLE_INVENTORY_FILENAME = 'hosts.{action_name}'
