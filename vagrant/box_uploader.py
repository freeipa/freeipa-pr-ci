#!/usr/bin/python

import argparse
import logging
import os
import yaml

from atlas import Context

def _get_user_config(user_config_path=None):
    if not user_config_path:
        user_config_path = os.path.join(
            os.environ.get(
                'XDG_CONFIG_HOME',
                os.path.expanduser('~/.config')
            ),
            'atlas_box_uploader.yaml',
        )

    try:
        with open(user_config_path) as user_config_file:
            user_config = yaml.load(user_config_file)
    except IOError as e:
        logger.error(
            'Unable to open user config file (user_config_path): {}'.format(e))
        raise

    try:
        user_config['url']
        user_config['username']
        user_config['token']
    except KeyError as e:
        logger.error('Missing {} in user config file'.format(e))
        raise

    return user_config


def create_parser():
    parser = argparse.ArgumentParser('Upload vagrant box to HashiCorp Atlas.')
    parser.add_argument('name', type=str, help='name of the box visible in Atlas')
    parser.add_argument('box', type=file, help='box to upload')
    parser.add_argument('-d', '--description', type=str)
    parser.add_argument('-p', '--provider', type=str, default='libvirt',
                        help='provider that box run on')
    parser.add_argument('-c', '--config-file', type=str,
                        help='user configuration file')

    group_version = parser.add_mutually_exclusive_group()
    group.add_argument('-v', '--version', type=str, default='revision',
                       help='upload Box as this version')
    group.add_argument('-M', '--bump-major', type=bool, default=False,
                       action='store_const', const='major', target='version',
                       help='use latest box version and bump major')
    group.add_argument('-m', '--bump-minor',  type=bool, default=False,
                       action='store_const', const='minor', target='version',
                       help='use latest box version and bump minor')
    group.add_argument('-r', '--bump-revision',  type=bool, default=False,
                       action='store_const', const='revision', target='version',
                       help='use latest box version and bump minor')

    return parser
    

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)

    args = create_parser().parse_args()

    box_name = args['name']
    box_version = args['version']
    box_filename = args['box'].name
    config_file = args['config-file']
    provider = args['provider']

    user_config = _get_user_config(config_file)

    context = Context(url=user_config['url'], username=user_config['username'],
                      token=user_config['token'])

    try:
        box = context.boxes[box_name]
    except KeyError:
        box = context.add_box(box_name)


    if box_version in {'major', 'minor', 'revision'}:
        try:
            major, minor, revision = [int(i) for i in box.versions.max().split('.')]
        except ValueError:
            box_version = '0.0.0'
        else:
            if box_version == 'major':
                major += 1
                minor = 0
                revision = 0
            elif box_version == 'minor':
                minor += 1
                revision = 0
            elif box_version == 'revision':
                revision = +1

            box_version = '{}.{}.{}'.format(major, minor, revision)

    try:
        version = box.versions[box_version]
    except KeyError:
        version = box.add_version(box_version)

    provider = version.add_provider(provider, box_filename)
