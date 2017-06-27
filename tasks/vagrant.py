import logging
import os
from pyvagrantfile.Parser import VagrantParser

from common import PopenTask, PopenException, FallibleTask, TaskException


class VagrantTask(FallibleTask):
    def __init__(self, **kwargs):
        super(VagrantTask, self).__init__(**kwargs)
        self.timeout = kwargs.get('timeout', None)


class VagrantUp(VagrantTask):
    def _run(self):
        self.execute_subtask(
            PopenTask(['vagrant', 'up', '--no-provision', '--parallel']))


class VagrantProvision(VagrantTask):
    def _run(self):
        self.execute_subtask(
            PopenTask(['vagrant', 'provision']))


class VagrantCleanup(VagrantTask):
    def _run(self):
        try:
            self.execute_subtask(
                PopenTask(['vagrant', 'destroy']))
        except PopenException:
            self.execute_subtask(
                PopenTask(['pkill', '-9', 'bin/vagrant'],
                          raise_on_err=False))
            self.execute_subtask(
                PopenTask(['systemctl', 'restart', 'libvirt'],
                          raise_on_err=False))
            self.execute_subtask(
                PopenTask(['vagrant', 'destroy'],
                          raise_on_err=False))


class VagrantBoxDownload(VagrantTask):
    def __init__(self, path=None, **kwargs):
        super(VagrantBoxDownload, self).__init__(**kwargs)
        self.path = path

    def _run(self):
        raise NotImplementedError
        # FIXME pyvagrantfile hangs on our vagrantfile for some reason
        vagrantfile = self.get_vagrantfile()
        box = VagrantBox.from_vagrantfile(vagrantfile)
        if not box.exists():
            try:
                self.execute_task(
                    PopenTask([
                        'vagrant', 'box', 'add', box.name,
                        '--box-version', box.version,
                        '--provider', box.provider]))
            except TaskException as exc:
                # TODO handle PopenException: remove older versions and retry?
                logging.warning("Box download failed")
                raise exc

    def get_vagrantfile(self):
        raise NotImplementedError
        path = self.vagrantfile
        if self.path is not None:
            path = os.path.join(self.path, path)
        try:
            with open(path) as vf:
                content = vf.read()
        except (OSError, IOError):
            raise TaskException(self, 'unable to open "{path}"'.format(
                path=path))
        return VagrantParser.parses(content=content)


class VagrantBox(object):
    def __init__(self, name, version, provider="libvirt"):
        self.name = name
        self.version = version
        self.provider = provider

    @staticmethod
    def from_vagrantfile(vagrantfile):
        try:
            box = vagrantfile.vm.box
            box_version = vagrantfile.vm.box_version
        except AttributeError:
            raise KeyError('vm.box or vm.box_config not found in vagrantfile')
        return VagrantBox(box, box_version)

    def exists(self):
        cmd = (
            'vagrant box list | '
            'grep -e "{name}\s\+({provider},\s\+{version}"').format(
                name=self.name,
                provider=self.provider,
                version=self.version)
        task = PopenTask(cmd, shell=True, raise_on_err=False)
        self.execute_subtask(task)
        return task.returncode == 0
