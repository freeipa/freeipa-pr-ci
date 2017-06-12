import logging
from task import PopenTask, TimeoutException, TaskException, TaskSequence
from vagrant import VagrantBoxDownload
import pytest
import os


def test_timeout():
    PopenTask(['sleep', '0.1'])()
    PopenTask(['sleep', '0.1'], timeout=0.2)()

    task = PopenTask(['sleep', '0.1'], timeout=0.01)
    with pytest.raises(TimeoutException) as exc_info:
        task()
    assert exc_info.value.task == task


def test_fallible_task():
    task = PopenTask(['ls', '/tmp/ag34feqfdafasdf'])
    with pytest.raises(TaskException) as exc_info:
        task()
    assert exc_info.value.task == task
    assert task.returncode != 0

    task = PopenTask(['ls', '/tmp/ag34feqfdafasdf'], severity=logging.WARNING)
    task()
    assert task.returncode != 0


def test_task_sequence():
    seq = TaskSequence([
        PopenTask(['touch', '/tmp/dfssdgadg15']),
        PopenTask(['rm', '/tmp/dfssdgadg15'])
    ])
    seq()

    fail_task = PopenTask(['rm', '/tmp/dfssdgadg15'])
    seq.append(fail_task)
    with pytest.raises(TaskException) as exc_info:
        seq()
    assert exc_info.value.task == fail_task


def test_task_sequence_timeout():
    seq = TaskSequence()
    seq.append(PopenTask(['sleep', '0.1'], timeout=0.2))
    timeout_task = PopenTask(['sleep', '0.1'], timeout=0.01)
    seq.append(timeout_task)
    with pytest.raises(TimeoutException) as exc_info:
        seq()
    assert exc_info.value.task == timeout_task


def test_popen():
    task = PopenTask(['ls', '/tmp'])
    task()
    assert task.returncode == 0

    task = PopenTask(['ls', '/tmp/adsdasafgsag'], severity=logging.WARNING)
    task()
    assert task.returncode == 2

    PopenTask('for i in `seq 3`; do echo $i; done', shell=True)()

    task = PopenTask('ls /tmp/$DIR', shell=True, severity=logging.WARNING)
    task()
    assert task.returncode == 0

    env = dict(DIR='gfdsgsdfgsfd')
    task = PopenTask('ls /tmp/$DIR', shell=True, env=env, severity=logging.WARNING)
    task()
    assert task.returncode == 2


def test_vagrant_box_download():
    path = os.path.dirname(os.path.realpath(__file__))
    task = VagrantBoxDownload(
        vagrantfile='Vagrantfile.mock',
        path=os.path.dirname(os.path.realpath(__file__)))
    vagrantfile = task.get_vagrantfile()

    assert vagrantfile.vm.box == 'freeipa/ci-master-f25'
    assert vagrantfile.vm.box_version == '0.2.5'

