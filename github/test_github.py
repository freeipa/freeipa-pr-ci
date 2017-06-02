import colorsys
import github3
import math
import operator
import pytest
import threading
import time
import yaml

from prci_github import get_pull_priority
from prci_github import PullQueue, TaskQueue
from prci_github import NoTaskAvailable, TaskAlreadyTaken, AbstractJob

with open('test_github.yaml') as f:
    gh_config = yaml.load(f)
GH_REPO = gh_config['repo']
GH_TOKEN = gh_config['token']
PULL_COUNT = 10
PRIORITY_COUNT = 3
branch_name_template = 'test_branch_{{:0{}d}}'.format(int(math.ceil(math.log(PULL_COUNT, 10))))
pull_title_template = 'PR #{{:0{}d}}'.format(int(math.ceil(math.log(PULL_COUNT, 10))))
label_priority_template = 'priority:{{:0{}d}}'.format(int(math.ceil(math.log(PRIORITY_COUNT, 10))))

def __colours(num):
    res = []
    for h in range(0, 80, 80/num):
        rgb_floats = colorsys.hsv_to_rgb(h/100., 0.9, 0.9)
        rgb_ints = tuple(int(comp*255) for comp in rgb_floats)
        rgb = (rgb_ints[0] << 16) + (rgb_ints[1] << 8) + rgb_ints[2]
        res.append('#{:06x}'.format(rgb))

    return res


def ismonotonic(seq, op):
    items = iter(seq)

    try:
        prev = next(items)
    except StopIteration:
        return True

    for item in items:
        if not op(prev, item):
            return False
        prev = item
    return True


class J(AbstractJob):
    def __call__(self):
        dep_results = {}
        for task_name, result in self.depends_results.items():
            desc, url = result
            dep_results['{}_description'.format(task_name)] = desc
            dep_resutls['{}_url'.format(task_name)] = url

        cmd = self.cmd.format(
            repo_url=self.target[0],
            pull_ref=self.target[1],
            **dep_results
        )

        import subprocess
        url = subprocess.check_output(build, shell=True)

        return (True, url)


@pytest.fixture(scope='module')
def repo(request):
    gh = github3.login(token=GH_TOKEN)
    repo = gh.create_repository(
        GH_REPO,
        has_issues=False,
        has_wiki=False,
        auto_init=True
    )

    labels_colours = __colours(PRIORITY_COUNT)
    for p in range(PRIORITY_COUNT):
        repo.create_label(
            label_priority_template.format(p),
            labels_colours[p],
        )
    while True:
        try:
            master_branch = repo.ref('heads/master')
        except github3.exceptions.ClientError as e:
            time.sleep(1)
        else:
            if isinstance(master_branch, github3.git.Reference):
                time.sleep(1)
                break

    for num in range(PULL_COUNT):
        branch_name = branch_name_template.format(num+1)
        pull_title = pull_title_template.format(num+1)

        # create a tree object containing the change
        tree = repo.create_tree(
            tree=[{
                'path': 'new file',
                'mode': '100644',
                'type': 'blob',
                'content': "content of new file",
            }],
            base_tree=repo.tree(master_branch.object.sha).sha,
        )

        # commit the change
        commit = repo.create_commit(
            message='Add new file',
            tree=tree.sha,
            parents=[master_branch.object.sha],
        )
        # create new branch pointing to the new commit
        repo.create_ref(
            'refs/heads/{}'.format(branch_name),
            commit.sha,
        )

        # create pull request from branch
        pull = repo.create_pull(
            title=pull_title,
            head=branch_name,
            base='master',
        )

        pull.issue().add_labels(label_priority_template.format(num % PRIORITY_COUNT))

    request.addfinalizer(repo.delete)

    return repo

class TestPRCI(object):
    def test_repo_creation(self, repo):
        assert len(list(repo.pull_requests())) == PULL_COUNT

    def test_iter_pulls_by_priority(self, repo):
        priorities = [get_pull_priority(p) for p in PullQueue(repo)]

        # assert that the sequence is nonincreasing
        assert ismonotonic(priorities, operator.ge), (
            "Priorities are not nonincreasing: {}".format(priorities))

    def test_task_queue_ordering(self, repo):
        tq = TaskQueue(repo, 'test_tasks.yaml', J)
        tq.create_tasks_for_pulls()

        tasks_done = []

        for task in tq:
            try:
                task.take('R#0')
            except TaskAlreadyTaken:
                continue
            else:
                task.execute()

            tasks_done.append({
                'pull_num': task.pull.number,
                'pull_prio': get_pull_priority(task.pull), 
                'task_name': task.name,
                'task_prio': task.priority,
            })

        pull_prios = [t['pull_prio'] for t in tasks_done]
        task_prios = {
            p: [t['task_prio'] for t in tasks_done if t['pull_num'] == p]
            for p in set([n['pull_num'] for n in tasks_done])
        }

        # pull request priority is nonincreasing
        assert ismonotonic(pull_prios, operator.ge)

        # within one pull request tasks priorities are nonincreasing
        assert all([ismonotonic(task_prios[p], operator.ge) for p in task_prios])
