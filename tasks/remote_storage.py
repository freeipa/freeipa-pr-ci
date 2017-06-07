from task import PopenTask, TaskException
import re


# TODO Set up proper ipa-maint account and ssh key
FEDORAPEOPLE_KEY_PATH='/home/sharp/.ssh/fedorapeople'
FEDORAPEOPLE_DIR='tkrizek@fedorapeople.org:/srv/groups/freeipa/prci/{path}'

BUILD_RE='\d{14}\+git[0-9a-f]{7}'


class RsyncTask(PopenTask):
    def __init__(self, src, dest, extra_args=None):
        if extra_args is None:
            extra_args = []

        cmd = [
            'rsync',
            '-r',
            src,
            dest
        ]
        cmd[2:2] = extra_args  # Extend argument list at index 2

        super(RsyncTask, self).__init__(cmd)


class SshRsyncTask(RsyncTask):
    def __init__(self, src, dest, extra_args=None, ssh_private_key_path=None):
        if extra_args is None:
            extra_args = []

        if ssh_private_key_path is not None:
            extra_args.extend([
                '-e',
                ('ssh -i {key} '
                 '-o "StrictHostKeyChecking no" '
                 '-o "UserKnownHostsFile=/dev/null"'
                ).format(key=ssh_private_key_path)
            ])

        super(SshRsyncTask, self).__init__(src, dest, extra_args)


class FedoraPeopleUpload(SshRsyncTask):
    def __init__(self, src):
        if not src.endswith('/'):
            src += '/'

        match = re.match(BUILD_RE + '/(.*/)?$', src)
        if not match:
            raise TaskException(
                "Directory has to start with: YYYYMMDDHHMMSS+git<sha>")

        super(FedoraPeopleUpload, self).__init__(
            src,
            FEDORAPEOPLE_DIR.format(path=''),
            extra_args=['-R'],  # No need to create dirs with relative path
            ssh_private_key_path=FEDORAPEOPLE_KEY_PATH
        )


class FedoraPeopleDownload(SshRsyncTask):
    def __init__(self, build):
        match = re.match(BUILD_RE + '$')
        if not match:
            raise TaskException("Invalid build number: {build}".format(build))

        super(FedoraPeopleDownload, self).__init__(
            FEDORAPEOPLE_DIR.format(path=src),
            './',
            ssh_private_key_path=FEDORAPEOPLE_KEY_PATH
        )

