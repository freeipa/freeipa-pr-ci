import abc
import logging
import subprocess
import threading


FORMAT = '%(asctime)-15s %(levelname)8s  %(message)s'
logging.basicConfig(level=logging.DEBUG, format=FORMAT)


class Task(object):
    __metaclass__ = abc.ABCMeta
    def __init__(self):
        self.process = None
        self.returncode = None

    @abc.abstractmethod
    def _target():
        pass

    def run(self, timeout=None):
        thread = threading.Thread(target=self._target)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            self.process.terminate()
            thread.join()
        return self.returncode


class PopenTask(Task):
    def __init__(self, cmd):
        super(PopenTask, self).__init__()
        self.cmd = cmd

    def _target(self):
        self.process = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for line in iter(self.process.stdout.readline, b''):
            logging.debug(line.rstrip('\n'))
        self.process.wait()
        self.returncode = self.process.returncode


class TaskException(Exception):
    pass

