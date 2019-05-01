#!/usr/bin/python3

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
            user_config = yaml.full_load(user_config_file)
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

    def read_from_file(path):
        try:
            with open(path) as f:
                return f.read()
        except IOError as e:
            raise argparse.ArgumentTypeError(e)

    def log_level(level):
        try:
            return getattr(logging, level.upper())
        except AttributeError:
            raise argparse.ArgumentTypeError(
                '{} is not valid logging level'.format(level))

    parser = argparse.ArgumentParser(description='Upload vagrant box to HashiCorp Atlas.')
    parser.add_argument('name', type=str, help='name of the box visible in Atlas')
    parser.add_argument('box', type=open, help='box to upload')

    group = parser.add_mutually_exclusive_group()
    group.add_argument('--box-description', type=str)
    group.add_argument('--box-description-file', type=read_from_file, dest='box_description')

    group = parser.add_mutually_exclusive_group()
    group.add_argument('--box-short-description', type=str)
    group.add_argument('--box-short-description-file', type=read_from_file, dest='box_short_description')

    group = parser.add_mutually_exclusive_group()
    group.add_argument('--version-description', type=str)
    group.add_argument('--version-description-file', type=read_from_file, dest='version_description')

    parser.add_argument('--provider', type=str,
                        help='provider that box run on (libvirt by default)')
    parser.add_argument('--config-file', type=str,
                        help='user configuration file')

    group = parser.add_argument_group('Logging')
    group.add_argument('--log-level', type=log_level)
    group.add_argument('--log-facility', type=str, nargs='*')

    group = parser.add_mutually_exclusive_group()
    group.add_argument('--version', action='store',
                       help='upload Box as this version')
    group.add_argument('--bump-major', action='store_const',
                       const='major', dest='version',
                       help='use latest box version and bump major')
    group.add_argument('--bump-minor', action='store_const',
                       const='minor', dest='version',
                       help='use latest box version and bump minor')
    group.add_argument('--bump-revision', action='store_const',
                       const='revision', dest='version',
                       help='use latest box version and bump minor')

    # defaults
    parser.set_defaults(provider='libvirt')
    parser.set_defaults(log_level='warning')
    parser.set_defaults(version='revision')

    return parser

def get_next_version(box, box_version_arg):
    if box_version_arg in {'major', 'minor', 'revision'}:
        try:
            major, minor, revision = [int(i) for i in box.versions.max().split('.')]
        except ValueError:
            box_version = '0.0.0'
        else:
            if box_version_arg == 'major':
                major += 1
                minor = 0
                revision = 0
            elif box_version_arg == 'minor':
                minor += 1
                revision = 0
            elif box_version_arg == 'revision':
                revision += 1

            box_version = '{}.{}.{}'.format(major, minor, revision)
    else:
        box_version = box_version_arg

    return box_version


if __name__ == '__main__':
    args = create_parser().parse_args()

    logging.basicConfig(level=args.log_level)
    logger = logging.getLogger('box_uploader')

    box_name = args.name
    box_short_description = args.box_short_description
    box_description = args.box_description
    box_version = args.version
    box_filename = args.box.name
    config_file = args.config_file
    box_provider = args.provider
    version_description = args.version_description

    user_config = _get_user_config(config_file)

    context = Context(url=user_config['url'], username=user_config['username'],
                      token=user_config['token'])

    try:
        box = context.boxes[box_name]
    except KeyError:
        box = context.add_box(box_name, short_description=box_short_description,
                              description=box_description)

    box_version = get_next_version(box, box_version)

    try:
        version = box.versions[box_version]
    except KeyError:
        version = box.add_version(box_version, description=version_description)

    try:
        provider = version.providers[box_provider]
    except KeyError:
        provider = version.add_provider(box_provider)

    try:
        provider.upload(box_filename)
    except Exception:
        # for unknown reason there's BadStatusLine exception after
        # successful upload, ignore
        # TODO: investigate and fix properly/report to vagrant cloud
        pass

    version.release()
