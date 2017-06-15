import re

from common import PopenTask, TaskException


# TODO Set up proper ipa-maint account and ssh key
FEDORAPEOPLE_KEY_PATH = '/home/sharp/.ssh/fedorapeople'
FEDORAPEOPLE_DIR = 'tkrizek@fedorapeople.org:/srv/groups/freeipa/prci/{path}'

BUILD_RE = '\d{14}\+git[0-9a-f]{7}'


class GzipLogFiles(PopenTask):
    def __init__(self, directory, **kwargs):
        super(GzipLogFiles, self).__init__(self, **kwargs)
        self.directory = directory
        self.cmd = (
            'find {directory} '
            '-type f '
            '! -name "*.gz" '
            '-a ! -name "*.rpm" '
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
    def __init__(self, src, **kwargs):
        if not src.endswith('/'):
            src += '/'

        match = re.match(BUILD_RE + '/(.*/)?$', src)
        if not match:
            raise TaskException(
                self,
                "Directory has to start with: YYYYMMDDHHMMSS+git<sha>")

        super(FedoraPeopleUpload, self).__init__(
            src,
            FEDORAPEOPLE_DIR.format(path=''),
            extra_args=['-R'],  # No need to create dirs with relative path
            ssh_private_key_path=FEDORAPEOPLE_KEY_PATH,
            **kwargs
        )


class FedoraPeopleDownload(SshRsyncTask):
    def __init__(self, build, **kwargs):
        match = re.match(BUILD_RE + '$', build)
        if not match:
            raise TaskException(
                self,
                "Invalid build id: {build}".format(build=build))

        super(FedoraPeopleDownload, self).__init__(
            FEDORAPEOPLE_DIR.format(path=build),
            './',
            ssh_private_key_path=FEDORAPEOPLE_KEY_PATH,
            **kwargs
        )
