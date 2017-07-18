import os
import re

from .common import PopenTask, TaskException
from .constants import (FEDORAPEOPLE_KEY_PATH, FEDORAPEOPLE_DIR, UUID_RE,
                        JOBS_DIR)


class GzipLogFiles(PopenTask):
    def __init__(self, directory, **kwargs):
        super(GzipLogFiles, self).__init__(self, **kwargs)
        self.directory = directory
        self.cmd = (
            'find {directory} '
            '-type f '
            '! -path "*/.vagrant/*" '
            '-a ! -path "*/rpms/*" '
            '-a ! -name "*.gz" '
            '-a ! -name "Vagrantfile" '
            '-a ! -name "ipa-test-config.yaml" '
            '-a ! -name "vars.yml" '
            '-a ! -name "ansible.cfg" '
            '-a ! -name "report.html" '
            '-exec gzip "{{}}" \;'
        ).format(directory=directory)
        self.shell = True


class RsyncTask(PopenTask):
    def __init__(self, src, dest, extra_args=None, **kwargs):
        if extra_args is None:
            extra_args = []

        cmd = [
            'rsync',
            '-r',
            '--chmod=0755',
            src,
            dest
        ]
        cmd[2:2] = extra_args  # Extend argument list at index 2

        super(RsyncTask, self).__init__(cmd, **kwargs)


class SshRsyncTask(RsyncTask):
    def __init__(self, src, dest, extra_args=None, ssh_private_key_path=None,
                 **kwargs):
        if extra_args is None:
            extra_args = []

        if ssh_private_key_path is not None:
            extra_args.extend([
                '-e',
                (
                    'ssh -i {key} '
                    '-o "StrictHostKeyChecking no" '
                    '-o "UserKnownHostsFile /dev/null" '
                    '-o "LogLevel ERROR"'
                ).format(key=ssh_private_key_path)
            ])

        super(SshRsyncTask, self).__init__(src, dest, extra_args, **kwargs)


class FedoraPeopleUpload(SshRsyncTask):
    def __init__(self, uuid, **kwargs):
        if not re.match(UUID_RE, uuid):
            raise TaskException(self, "Invalid job UUID")

        super(FedoraPeopleUpload, self).__init__(
            os.path.join(JOBS_DIR, uuid),
            FEDORAPEOPLE_DIR.format(path='jobs/'),
            ssh_private_key_path=FEDORAPEOPLE_KEY_PATH,
            **kwargs
        )


class FedoraPeopleDownload(SshRsyncTask):
    def __init__(self, uuid, **kwargs):
        if not re.match(UUID_RE, uuid):
            raise TaskException(self, "Invalid job UUID")

        super(FedoraPeopleDownload, self).__init__(
            FEDORAPEOPLE_DIR.format(path='jobs/' + uuid),
            JOBS_DIR,
            ssh_private_key_path=FEDORAPEOPLE_KEY_PATH,
            **kwargs
        )
