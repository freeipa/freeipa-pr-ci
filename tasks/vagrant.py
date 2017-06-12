from logging import WARNING, INFO
from tasks.task import PopenTask, PopenException, FallibleTask, TaskException
from pyvagrantfile.Parser import VagrantParser
import os


class VagrantTask(FallibleTask):
    def __init__(self, vagrantfile='Vagrantfile', **kwargs):
        super(VagrantTask, self).__init__(**kwargs)
        self.vagrantfile = vagrantfile
        self.env = {'VAGRANTFILE': vagrantfile}
        

class VagrantCleanup(VagrantTask):
    def _run(self):
        try:
            PopenTask(['vagrant', 'destroy'], env=self.env, timeout=60)()
        except PopenException:
            PopenTask(['pkill', '-9', 'bin/vagrant'],
                severity=WARNING, env=self.env, timeout=60)()
            PopenTask(['systemctl', 'restart', 'libvirt'],
                severity=WARNING, env=self.env, timeout=60)()
            PopenTask(['vagrant', 'destroy'],
                severity=WARNING, env=self.env, timeout=60)()


class VagrantBoxDownload(VagrantTask):
    def __init__(self, path=None, **kwargs):
        super(VagrantBoxDownload, self).__init__(**kwargs)
        self.path = path

    def _run(self):
        vagrantfile = self.get_vagrantfile()
        box = VagrantBox.from_vagrantfile(vagrantfile)
        if not box.exists():
            try:
                PopenTask([
                    'vagrant', 'box', 'add', box.name,
                    '--box-version', box.version,
                    '--provider', box.provider])()
            except TaskException as exc:
                # TODO handle PopenException: remove older versions and retry?
                logging.log(self.severity, "Box download failed")
                raise exc

    def get_vagrantfile(self):
        path = self.vagrantfile
        if self.path is not None:
            path = os.path.join(self.path, path)
        try:
            with open(path) as vf:
                content = vf.read()
        except (OSError, IOError) as exc:
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
        task = PopenTask(cmd, shell=True, severity=INFO)
        task()
        return task.returncode == 0

