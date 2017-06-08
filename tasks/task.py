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
    def __init__(self, cmd, failure_severity=logging.ERROR):
        super(PopenTask, self).__init__()
        self.cmd = cmd
        self.loglvl = failure_severity

    def _target(self):
        self.process = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for line in iter(self.process.stdout.readline, b''):
            logging.debug(line.rstrip('\n'))
        for line in iter(self.process.stderr.readline, b''):
            logging.log(self.loglvl, line)
        self.process.wait()
        self.returncode = self.process.returncode
        if self.loglvl >= logging.ERROR and self.returncode != 0:
            raise TaskException(
                'Process exited with error code: {returncode}'.format(
                    returncode=self.returncode))


class TaskException(Exception):
    pass

