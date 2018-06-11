import abc
import collections
import errno
import logging
import os
import signal
import subprocess
import threading
from typing import Callable, List, Text

import jinja2
import psutil

from . import constants

LOG_FILE_HANDLER = None
LOG_FORMAT = '%(asctime)-15s %(levelname)8s  %(message)s'


PopenFileType = type(psutil._pslinux.popenfile)
KillPredicateType = Callable[[PopenFileType], bool]


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
        self.msg = 'timed out after {timeout}s'.format(
            timeout=self.task.timeout)


class PopenException(TaskException):
    def __init__(self, task):
        super(PopenException, self).__init__(task)
        self.msg = 'exited with error code {error}'.format(
            error=self.task.returncode)


class Task(collections.Callable):
    __metaclass__ = abc.ABCMeta

    def __init__(self, timeout=120):
        self.timeout = timeout
        self.tasks = []
        self.exc = None

    def execute_subtask(self, task):
        """
        Make sure to use this function to execute all children tasks.

        This is needed to make sure the timeout works properly. If you run
        the task directly and the timeout mechanic is triggered, it won't be
        able to kill the child process and the timeout won't work properly.
        """
        self.tasks.append(task)
        task()

    @abc.abstractmethod
    def _run(self):
        pass

    def _before(self):
        pass

    def _after(self):
        pass

    def _terminate(self):
        pass

    def terminate(self):
        for task in self.tasks:
            task.terminate()
        self._terminate()

    def __target(self):
        self.exc = None
        try:
            try:
                self._before()
                self._run()
            finally:
                self._after()
        except Exception as exc:
            self.exc = exc

    def __call__(self):
        logging.info('Executing: {task}'.format(task=self))
        thread = threading.Thread(target=self.__target)
        thread.start()
        thread.join(self.timeout)
        if thread.is_alive():
            self.terminate()
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
        except Exception as exc:
            if self.raise_on_err:
                logging.debug(exc, exc_info=True)
                raise exc
            else:
                logging.warning(exc, exc_info=True)


class PopenTask(FallibleTask):
    def __init__(self, cmd, shell=False, env=None, **kwargs):
        super(PopenTask, self).__init__(**kwargs)
        self.cmd = cmd
        self.shell = shell
        self.env = env
        self.process = None
        self.returncode = None
        if self.env is not None:
            self.env = os.environ.copy()
            self.env.update(env)

    def _run(self):
        self.process = subprocess.Popen(
            self.cmd,
            shell=self.shell,
            env=self.env,
            preexec_fn=os.setsid,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT)

        for line in iter(self.process.stdout.readline, b''):
            logging.debug(line.decode('utf-8').rstrip('\n'))

        self.process.wait()
        self.returncode = self.process.returncode
        self.process = None
        if self.returncode != 0:
            raise PopenException(self)

    def _terminate(self):
        if self.process is None:
            return

        # Make sure every child process is gone
        os.killpg(self.process.pid, signal.SIGKILL)
        # Make sure every Vagrant process and VM process is gone
        kill_vagrant_processes()
        kill_vagrant_vms()

    def __str__(self):
        if not isinstance(self.cmd, str):
            cmd = ' '.join(self.cmd)
        else:
            cmd = self.cmd
        return 'Process "{cmd}"'.format(cmd=cmd)


def logging_init_stream_handler(noout=False):
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    if noout:
        ch.setLevel(logging.CRITICAL+1)
    formatter = logging.Formatter(LOG_FORMAT)
    ch.setFormatter(formatter)
    logger.addHandler(ch)


def logging_init_file_handler():
    global LOG_FILE_HANDLER
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(constants.RUNNER_LOG, mode='w')
    fh.setLevel(logging.DEBUG)
    formatter = logging.Formatter(LOG_FORMAT)
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    LOG_FILE_HANDLER = fh


def create_file_from_template(template_path, dest, data):
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(constants.TEMPLATES_DIR))
    template = env.get_template(template_path)
    rendered_template = template.render(**data)

    with open(dest, "w") as fh:
        fh.write(rendered_template)


def get_processes(pname: Text) -> List[psutil.Process]:
    """Gets all of the processes by name"""
    return [
        proc for proc in psutil.process_iter(
            attrs=["pid", "name", "open_files"]
        ) if pname in proc.info["name"]
    ]


def kill_processes(proc_list: List[psutil.Process],
                   kill_predicate: KillPredicateType) -> None:
    """Kills the processes using given predicate"""
    for proc in proc_list:
        open_files = proc.info["open_files"]
        if open_files is None:
            continue
        for open_file in open_files:
            if kill_predicate(open_file):
                proc.send_signal(signal.SIGKILL)


def get_ruby_processes() -> List[psutil.Process]:
    """Because every Vagrant process is just a Ruby one"""
    return get_processes("ruby-mri")


def get_qemu_processes() -> List[psutil.Process]:
    """Fetches every QEMU process on the host"""
    return get_processes("qemu-system-x86_64")


def kill_vagrant_processes() -> None:
    """Kills all of Vagrant processes"""
    return kill_processes(get_ruby_processes(), lambda f: "vagrant" in f.path)


def kill_vagrant_vms() -> None:
    """Kills all of Vagrant created VMs"""
    def predicate(f: PopenFileType) -> bool:
        roles = ["master", "replica", "controller", "client"]
        return any([role in f.path for role in roles])

    return kill_processes(get_qemu_processes(), predicate)
