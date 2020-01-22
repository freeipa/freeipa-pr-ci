import json
import logging
import os
import pathlib

import requests
from flask import Flask, make_response, request
from requests.exceptions import RequestException

VAGRANT_URL = 'https://app.vagrantup.com/{user_name}/boxes/{box_name}.json'
CATALOG_PATH = '/usr/share/nginx/html/catalog'

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)


def replace_box_domain(catalog, domain):
    '''Replace provider urls to point to `domain`.'''
    for ver_key, version in enumerate(catalog['versions']):
        for pro_key, provider in enumerate(version['providers']):
            new_url = provider['url'].replace(
                'https://vagrantcloud.com/', domain
            )
            catalog['versions'][ver_key]['providers'][pro_key]['url'] = new_url
    return catalog


def save_catalog(catalog_data, user_name, box_name):
    '''Save catalog file to `CATALOG_PATH/{user_name}/{box_name}.json`.'''
    app.logger.info(f'Saving catalog for {user_name}/{box_name}.')

    folder_path = os.path.join(CATALOG_PATH, user_name)
    pathlib.Path(folder_path).mkdir(parents=True, exist_ok=True)

    catalog_path = os.path.join(folder_path, box_name + '.json')

    with open(catalog_path, 'w', encoding='utf-8') as catalog_file:
        json.dump(catalog_data, catalog_file)


@app.route('/<user_name>/<box_name>')
def get_box(user_name, box_name):
    '''Fetch catalog from `VAGRANT_URL`, store and return original data.'''
    app.logger.info(f'Fetching catalog for {user_name}/{box_name}.')
    try:
        response = requests.get(
            VAGRANT_URL.format(user_name=user_name, box_name=box_name)
        )
        catalog = response.json()

        if response.status_code == requests.codes['ok']:
            domain = request.host_url
            catalog = replace_box_domain(catalog, domain)

            save_catalog(
                user_name=user_name, box_name=box_name, catalog_data=catalog,
            )

        return make_response(catalog, response.status_code)
    except RequestException:
        app.logger.exception(f'Error while fetching {user_name}/{box_name}.')
        return make_response(catalog, requests.codes['server_error'])
