#!/bin/env python3
import argparse
import logging
import os
import pathlib
import shutil
import subprocess
import sys

import requests
from requests.exceptions import RequestException

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

VAGRANT_URL = 'https://app.vagrantup.com/{user_name}/boxes/{box_name}.json'
CATALOG_PATH = '/usr/share/nginx/html'

BOX_PATH_PATTERN = (
    '{user_name}/boxes/{box_name}/versions/{box_version}/'
    'providers/{provider_name}.box'
)


def download_box(user_name, box_name, box_version):
    '''Download box to CATALOG_PATH, following the same structure as Vagrant.
    '''
    try:
        response = requests.get(
            VAGRANT_URL.format(user_name=user_name, box_name=box_name)
        )
        response.raise_for_status()
    except RequestException:
        logger.error(
            f'Could not fetch data for {user_name}/{box_name} ({box_version}).'
        )
        return 1
    data = response.json()

    try:
        versions = [v for v in data['versions'] if v['version'] == box_version]
        version = versions[0]
        if version['status'] != 'active':
            logger.error(f'Version "{box_version}" not active.')
            return
    except IndexError:
        logger.error(f'Version "{box_version}" not available.')
        return 1

    try:
        providers = [p for p in version['providers'] if p['name'] == 'libvirt']
        provider = providers[0]
    except IndexError:
        logger.error(f'Provider "libvirt" not available.')
        return 1

    temp_box_path = os.path.join(
        '/tmp/temp_boxes',
        BOX_PATH_PATTERN.format(
            user_name=user_name,
            box_name=box_name,
            box_version=box_version,
            provider_name='libvirt',
        ),
    )
    final_box_path = os.path.join(
        CATALOG_PATH,
        BOX_PATH_PATTERN.format(
            user_name=user_name,
            box_name=box_name,
            box_version=box_version,
            provider_name='libvirt',
        ),
    )

    logger.info(f'Downloading box to "{temp_box_path}".')

    subprocess.run([
        'curl',
        '-q',
        '--fail',
        '--location',
        '--create-dirs',
        # '--silent',
        '--continue-at',
        '-',
        '--output',
        temp_box_path,
        provider['url'],
    ])

    logger.info(f'Moving box to "{final_box_path}".')

    pathlib.Path(os.path.dirname(final_box_path)).mkdir(
        parents=True, exist_ok=True
    )
    shutil.move(temp_box_path, final_box_path)

    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='''
    Download a vagrant box to be stored and served by this machine.
    ''')

    parser.add_argument('user_name', help='User name of box owner.')
    parser.add_argument('box_name', help='Box name.')
    parser.add_argument('box_version', help='Box version.')

    parser.add_argument('--catalog-path', dest='catalog_path', type=str,
                        help=f'Where the box will be saved ({CATALOG_PATH}).',
                        default=CATALOG_PATH)

    args = parser.parse_args()

    # override constant
    CATALOG_PATH = args.catalog_path

    # Call function
    return_code = download_box(
        user_name=args.user_name,
        box_name=args.box_name,
        box_version=args.box_version,
    )
    sys.exit(return_code)
