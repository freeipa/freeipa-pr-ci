import os

from .common import PopenTask, FallibleTask, TaskException


class AnsibleFixKeysPermissions(FallibleTask):
    def __init__(self, directory='../keys', **kwargs):
        super(AnsibleFixKeysPermissions, self).__init__(**kwargs)
        self.directory = directory

    def _run(self):
        try:
            for file_ in os.listdir(self.directory):
                if not file_.endswith(".pub"):
                    os.chmod(os.path.join(self.directory, file_), 0o600)
        except (IOError, OSError):
            raise TaskException(self, 'unable to fix key permissions')


class AnsiblePlaybook(PopenTask):
    def __init__(self, playbook=None, extra_vars=None,
                 verbosity=None, **kwargs):
        if extra_vars is None:
            extra_vars = {}
        # use Python 3 as default Python interpreter for Ansible
        extra_vars.setdefault(
            'ansible_python_interpreter',
            '/usr/bin/python3'
        )
        self.extra_vars = extra_vars
        self.playbook = playbook
        self.verbosity = verbosity

        if self.playbook is None:
            raise TaskException(self, 'playbook is required')

        cmd = [
            "ansible-playbook",
            self.playbook]

        for name, value in self.extra_vars.items():
            if value is None:
                continue
            cmd[2:2] = ['-e', '{name}={value}'.format(
                name=name,
                value=value)]

        if self.verbosity is not None:
            cmd.append('-{verbosity}'.format(verbosity=self.verbosity))

        super(AnsiblePlaybook, self).__init__(cmd, **kwargs)
