import json
import os
import re
import socket
from datetime import datetime

import boto3
from jinja2 import Template

from .common import PopenTask, TaskException, FallibleTask
from .constants import (CLOUD_JOBS_DIR, CLOUD_JOBS_URL, CLOUD_URL, CLOUD_DIR,
                        CLOUD_BUCKET, CLOUD_DB, CLOUD_REGION, UUID_RE,
                        JOBS_DIR, TASKS_DIR)

"""
Previously we were updating test results in Fedora infra where the results were
directly served as part of web server directory listing capabilities. This is
not case of AWS S3.
In order to simulate same environment we are generating "index.html" using
Jinja2 template and putting it into every directory. Then we upload particular
job directory using awscli (which does parallelism for us) under S3 bucket
"jobs" prefix (directory). Currently 2 awscli commands are needed in order to
set correct encoding for gzip files. Content types are set automatically using
"/etc/mime.types" file.
At the end we create root jobs index to list all "freeipa" repo PR jobs in the
bucket.
"""


def create_jobs_root_index():
    """
    Generate root jobs index from AWS DynamoDB table.
    """
    client = boto3.client('s3')
    dynamodb = boto3.resource('dynamodb', region_name=CLOUD_REGION)
    table = dynamodb.Table(CLOUD_DB)

    response = table.scan()
    objects = response['Items']

    while response.get('LastEvaluatedKey'):
        response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
        objects.extend(response['Items'])

    obj_data = {'objects': objects}

    client.put_object(Body=generate_index(obj_data, is_root=True),
                      Bucket=CLOUD_BUCKET,
                      Key=os.path.join(CLOUD_JOBS_DIR, 'index.html'),
                      ContentEncoding='utf-8', ContentType='text/html')


def generate_index(obj_data, is_root=False):
    """
    Generate Jinja2 template for index.html with all AWS S3 objects
    (files and directories).
    For jobs index we use different template.
    """

    jinja_ctx = {'obj_data': obj_data, 'cloud_jobs_url': CLOUD_JOBS_URL,
                 'cloud_url': CLOUD_URL}

    if is_root:
        template = 'root_index_template.html'
    else:
        template = 'index_template.html'

    with open(os.path.join(TASKS_DIR, template), 'r') as file_:
        template = Template(file_.read())
    return template.render(jinja_ctx)


def write_index(data, path):
    """
    Write index.html into every directory (locally).
    """
    index_loc = os.path.join(path, 'index.html')
    with open(index_loc, 'w') as file_:
        file_.write(generate_index(data))


def make_object(root, obj):
    """
    Gather particular dir/file data.
    """
    fpath = os.path.join(root, obj)
    fstat = os.stat(fpath)
    mtime = datetime.fromtimestamp(fstat.st_mtime)
    size = fstat.st_size

    if os.path.isdir(fpath):
        o_type = "dir"
    else:
        o_type = "file"

    return {
        "name": obj, "mtime": mtime,
        "size": size, "type": o_type
    }


def make_objects(root, objects):
    """
    Go through subdirs and files in order to gather "object" data.
    """
    for f in objects:
        yield make_object(root, f)


def make_aws_data(remote_path, uuid, pr_number, pr_author, task_name,
                  returncode, hostname, objects):
    """
    Create AWS data for Jinja.
    """
    return {
        "remote_path": remote_path, "uuid": uuid, "pr_number": pr_number,
        "pr_author": pr_author, "task_name": task_name,
        "returncode": returncode, "hostname": hostname,"objects": objects
    }


def create_local_indeces(uuid, pr_number, pr_author, task_name, returncode,
                         hostname):
    """
    Go through whole job result directory structure and gather all files with
    metadata for every directory. Note: AWS S3 does not support classic web
    server browseability capabilities so we do this in order to avoid
    JavaScript solution on storage side. Also there is no concept of
    files/directories but rather objects. In this case it is more convenient
    to do this locally.
    """
    job_dir = os.path.join(JOBS_DIR, uuid)
    job_path_start = job_dir.rfind(os.sep) + 1
    for root, dirs, files in os.walk(job_dir):
        remote_path = root[job_path_start:]
        objects = list(make_objects(root, dirs + files))
        data = make_aws_data(
            remote_path, uuid, pr_number, pr_author,
            task_name, returncode, hostname, objects
        )
        write_index(data, root)


def save_jobdir_metadata(uuid, repo_owner, pr_number, pr_author, task_name,
                           returncode):
    """
    Update particular job dir metadata to DynamoDB table.
    """
    dynamodb = boto3.resource('dynamodb', region_name=CLOUD_REGION)
    table = dynamodb.Table(CLOUD_DB)

    table.put_item(
        Item={
            'name': uuid,
            'repo_owner': repo_owner,
            'pr_number': pr_number,
            'pr_author': pr_author,
            'task_name': task_name,
            'returncode': returncode,
            'mtime': datetime.now().strftime('%Y-%m-%d %H:%M'),
        }
    )


def create_metadata_json(src, uuid, repo_owner, pr_number, pr_author,
                         task_name, returncode):
    """
    Save particular job metadata into job UUID directory for external tools
    usage
    """
    metadata = {
        'name': uuid,
        'repo_owner': repo_owner,
        'pr_number': pr_number,
        'pr_author': pr_author,
        'task_name': task_name,
        'returncode': returncode,
        'mtime': datetime.now().strftime('%Y-%m-%d %H:%M'),
        }
    with open(os.path.join(src, 'metadata.json'), 'w') as file_obj:
        json.dump(metadata, file_obj)


class GzipLogFiles(PopenTask):
    def __init__(self, directory, **kwargs):
        super(GzipLogFiles, self).__init__(self, **kwargs)
        self.directory = directory
        self.cmd = (
            'find {directory} '
            '-type f '
            '! -path "*/.vagrant/*" '
            '-a ! -path "*/assets/*" '
            '-a ! -path "*/rpms/*" '
            '-a ! -name "*.gz" '
            '-a ! -name "*.png" '
            '-a ! -name "Vagrantfile" '
            '-a ! -name "ipa-test-config.yaml" '
            '-a ! -name "vars.yml" '
            '-a ! -name "ansible.cfg" '
            '-a ! -name "report.html" '
            '-exec gzip "{{}}" \;'
        ).format(directory=directory)
        self.shell = True


class CloudUpload(FallibleTask):
    """
    Upload PRCI job task artifacts to AWS S3 cloud.
    """
    def __init__(self, uuid, repo_owner, pr_number, pr_author, task_name,
                 returncode, **kwargs):
        if not re.match(UUID_RE, uuid):
            raise TaskException(self, "Invalid job UUID")
        super(CloudUpload, self).__init__(**kwargs)
        self.uuid = uuid
        self.repo_owner = repo_owner
        self.pr_number = str(pr_number) if not None else ''
        self.pr_author = pr_author if not None else ''
        self.task_name = task_name if not None else ''
        self.returncode = str(returncode) if not None else ''

    def _run(self):
        # make sure we don't leak fqdn
        self.hostname = socket.gethostname().split('.')[0]
        src = os.path.join(JOBS_DIR, self.uuid)
        dest = os.path.join(CLOUD_DIR, CLOUD_JOBS_DIR, self.uuid)

        create_metadata_json(src, self.uuid, self.repo_owner,
                             self.pr_number, self.pr_author,
                             self.task_name, self.returncode)

        create_local_indeces(self.uuid, self.pr_number, self.pr_author,
                             self.task_name, self.returncode, self.hostname)

        aws_sync_cmd = ['aws', 's3', 'sync', src, dest]
        sync_all_except_gz = ['--include=*', '--exclude=*.gz']
        sync_gz = ['--exclude=*', '--include=*.gz', '--content-encoding=gzip',
                   '--content-type=text/plain']

        # run 2 awscli commands so we can upload all "gzip" files with
        # correct encoding.
        self.execute_subtask(PopenTask(aws_sync_cmd + sync_all_except_gz))
        self.execute_subtask(PopenTask(aws_sync_cmd + sync_gz))


class CreateRootIndex(FallibleTask):
    """
    Create jobs root index
    """
    def __init__(self, uuid, repo_owner, pr_number, pr_author, task_name,
                 returncode, **kwargs):
        if not re.match(UUID_RE, uuid):
            raise TaskException(self, "Invalid job UUID")
        super(CreateRootIndex, self).__init__(**kwargs)
        self.uuid = uuid
        self.repo_owner = repo_owner
        self.pr_number = str(pr_number) if not None else ''
        self.pr_author = pr_author if not None else ''
        self.task_name = task_name if not None else ''
        self.returncode = str(returncode) if not None else ''

    def _run(self):
        save_jobdir_metadata(self.uuid, self.repo_owner,
                             self.pr_number, self.pr_author,
                             self.task_name, self.returncode)
        create_jobs_root_index()
