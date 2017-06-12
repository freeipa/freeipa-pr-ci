from logging import WARNING
import os
from tasks.task import PopenTask, TaskSequence, PopenException, FallibleTask


class VagrantTask(FallibleTask):
    def __init__(self, vagrantfile='Vagrantfile', **kwargs):
        super(VagrantTask, self).__init__(**kwargs)
        self.vagrantfile = vagrantfile
        self.env = os.environ.copy()
        # self.env['VAGRANTFILE'] = 
        

class VagrantCleanup(FallibleTask):
    def _run(self):
        try:
            PopenTask(['vagrant', 'destroy'], timeout=60)()
        except PopenException:
            PopenTask(['pkill', '-9', 'bin/vagrant'],
                severity=WARNING, timeout=60)()
            PopenTask(['systemctl', 'restart', 'libvirt'],
                severity=WARNING, timeout=60)()
            PopenTask(['vagrant', 'destroy'],
                severity=WARNING, timeout=60)()

