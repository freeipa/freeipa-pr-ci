import abc
import collections
import errno
import logging
import os
import subprocess
import threading


class TaskException(Exception):
    def __init__(self, task, msg=None):
        self.task = task
        if msg is None:
            self.msg = 'execution failed'
        else:
            self.msg = msg

    def __str__(self):
        return '{task} {msg}'.format(
            task=self.task,
            msg=self.msg)


class TimeoutException(TaskException):
    def __init__(self, task):
        super(TimeoutException, self).__init__(task)
        self.msg = 'timed out after {timeout}s'.format(timeout=self.task.timeout)


class PopenException(TaskException):
    def __init__(self, task):
        super(PopenException, self).__init__(task)
        self.msg = 'exited with error code {error}'.format(
            error=self.task.returncode)


class Task(collections.Callable):
    __metaclass__ = abc.ABCMeta
    def __init__(self, timeout=None):
        self.timeout = timeout
        self.process = None
        self.returncode = None
        self.exc = None

    @abc.abstractmethod
    def _run(self):
        pass

    def __target(self):
        self.exc = None
        try:
            self._run()
        except TaskException as exc:
            self.exc = exc

    def __call__(self):
        logging.info('Executing: {task}'.format(task=self))
        thread = threading.Thread(target=self.__target)
        thread.start()
        thread.join(self.timeout)
        if thread.is_alive():
            try:
                self.process.terminate()
            except OSError as exc:
                if exc.errno != errno.ESRCH:
                    # ESRCH -> process doesn't exist (already ended)
                    raise exc
            thread.join()
            raise TimeoutException(self)
        if self.exc is not None:
            # Re-raise exception from other thread
            raise self.exc

    def __str__(self):
        return type(self).__name__


class FallibleTask(Task):
    def __init__(self, raise_on_err=True, **kwargs):
        super(FallibleTask, self).__init__(**kwargs)
        self.raise_on_err = raise_on_err

    def __call__(self):
        try:
            super(FallibleTask, self).__call__()
        except TaskException as exc:
            if self.raise_on_err:
                raise exc
            else:
                logging.warning(exc)


class PopenTask(FallibleTask):
    def __init__(self, cmd, shell=False, env=None, **kwargs):
        super(PopenTask, self).__init__(**kwargs)
        self.cmd = cmd 
        self.shell = shell
        self.env = env
        if self.env is not None:
            self.env = os.environ.copy()
            self.env.update(env)

    def _run(self):
        self.process = subprocess.Popen(
            self.cmd,
            shell=self.shell,
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT)

        for line in iter(self.process.stdout.readline, b''):
            logging.debug(line.rstrip('\n'))

        self.process.wait()
        self.returncode = self.process.returncode
        if self.returncode != 0:
            raise PopenException(self)

    def __str__(self):
        if not isinstance(self.cmd, basestring):
            cmd = ' '.join(self.cmd)
        else:
            cmd = self.cmd
        return 'Process "{cmd}"'.format(cmd=cmd)


class TaskSequence(FallibleTask, collections.deque):
    def __init__(self, *args, **kwargs):
        super(TaskSequence, self).__init__(*args, **kwargs)

    def _run(self):
        for task in self:
            task()

