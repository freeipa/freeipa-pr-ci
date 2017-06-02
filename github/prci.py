import github3
import signal
import subprocess

from prci_github import TaskQueue, AbstractJob


def quit(signum, _ignore):
    done = True


class Job(AbstractJob):
    def __call__(self):
        cmd = self.cmd.format(target_refspec=self.target_refspec[0])
        ok = True
        try:
            url = subprocess.check_output(cmd)
        except CalledProcessError as e:
            if e.returncode == 1:
                ok = False
                url = ''
            else:
                raise

        return (ok, url,)

with open('freeipa_github.yaml') as f:
    config = yaml.load(f)

done = False
gh = github3.login(config['token'])
repo = gh.repository(config['repo'])
tq = TastQueue(repo, 'freeipa_tasks.yaml', Job)

signal.signal(signal.SIGINT, quit)
signal.signal(signal.SIGTERM, quit)
signal.signal(signal.SIGQUIT, quit)

while not done:
    tq.create_tasks_for_pulls()

    task = tq.next()

    try:
        task.take('R#0')
    except TaskAlreadyTaken:
        continue

    task.execute()
