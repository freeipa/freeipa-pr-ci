#!/usr/bin/python

import collections
import os
import requests
import timeit
import tqdm  # dnf install python{2,3}-tqdm
from urllib import urlencode
from urlparse import urljoin
import logging

logger = logging.getLogger('atlas')


def chunked_file_with_progressbar(f):
    pb = tqdm.tqdm(total=os.stat(f.name).st_size, unit='B', unit_scale=True)
    for chunk in f:
        pb.update(len(chunk))
        yield chunk
    pb.close()


class CRUD(object):
    path_template = {}
    primary_keys = set()
    data_keys = set()
    data_name = None

    @classmethod
    def _path(cls, method, **keys):
        return cls.path_template[method].format(**keys)

    @classmethod
    def _get_keys(cls, **kwargs):
        return {k: v for k, v in kwargs.items() if k in cls.primary_keys}

    @classmethod
    def _prepare_data(cls, **kwargs):
        return {cls.data_name: {
            k: v for k, v in kwargs.items() if k in cls.data_keys and v
        }}

    def _refresh(self):
        path = self._path('read', **self.keys)
        result = self.context.get(path)
        if 'success' in result and not result['success']:
            err_msg = ' '.join(result['errors'])
            logger.error('Failed to retrieve {}: {}'.format(
                self.__class__.__name__, err_msg))
            raise RuntimeError(err_msg)

        self.data = result

    def __init__(self, context, **kwargs):
        self.context = context
        self.keys = self._get_keys(**kwargs)
        self._refresh()

    @classmethod
    def create(cls, context, **kwargs):
        keys = cls._get_keys(**kwargs)
        path = cls._path('create', **keys)
        data = cls._prepare_data(**kwargs)

        try:
            context.post(path, data)
        except Exception as e:
            logger.error('Failed to create {}: {}'.format(cls.__name__, e))
            raise

    def update(self, **kwargs):
        path = self._path('update', **self.keys)
        data = self._prepare_data(**kwargs)

        try:
            return self.context.put(path, data)
        except Exception as e:
            logger.error('Failed to update {}: {}'.format(
                self.__class__.__name__, e))
            raise

    def delete(self):
        path = self._path('delete', **self.keys)
        try:
            return self.context.delete(path)
        except Exception as e:
            logger.error('Failed to delete {}: {}'.format(
                self.__class__.__name__, e))
            raise


class Boxes(object):
    def __init__(self, context):
        self.context = context

    def __getitem__(self, key):
        if isinstance(key, tuple):
            username = key[0]
            name = key[1]
        else:
            username = self.context.username
            name = key

        try:
            return Box(self.context, name, username)
        except Exception:
            raise KeyError(key)


class Mapping(collections.Mapping):
    obj_cls = None
    obj_key = None
    id_key = None

    def __init__(self, parent):
        self.parent = parent

    def __getitem__(self, key):
        try:
            return self.obj_cls(self.parent, key)
        except Exception:
            raise KeyError(key)

    def __iter__(self):
        self.parent._refresh()
        for item in self.parent.data[self.obj_key]:
            yield item[self.id_key]

    def __len__(self):
        return len(self.parent.data[self.obj_key])


class BoxProvider(CRUD):
    path_template = {
        'create': 'api/v1/box/{username}/{name}/version/{version}/providers',
        'read': 'api/v1/box/{username}/{name}/version/{version}/provider/{provider}',
        'update': 'api/v1/box/{username}/{name}/version/{version}/provider/{provider}',
        'delete': 'api/v1/box/{username}/{name}/version/{version}/provider/{provider}',
        'upload': 'api/v1/box/{username}/{name}/version/{version}/provider/{provider}/upload',
        'download': '{username}/{name}/version/{version}/providers/{provider}.box',
    }
    primary_keys = {'username', 'name', 'version', 'provider'}
    data_keys = {'provider', 'url'}
    data_name = 'provider'

    @classmethod
    def _prepare_data(cls, **kwargs):
        data = super(BoxProvider, cls)._prepare_data(**kwargs)
        data[cls.data_name]['name'] = data[cls.data_name].pop('provider')
        return data

    @classmethod
    def create(cls, boxversion, provider, url=None):
        return super(BoxProvider, cls).create(boxversion.context,
            name=boxversion.keys['name'], username=boxversion.keys['username'],
            version=boxversion.keys['version'], provider=provider, url=url)

    def __init__(self, boxversion, provider):
        super(BoxProvider, self).__init__(boxversion.context, 
            name=boxversion.keys['name'], username=boxversion.keys['username'],
            version=boxversion.keys['version'], provider=provider)

    def upload(self, boxpath):
        path = self._path('upload', **self.keys)
        try:
            url = self.context.get(path)
        except Exception as e:
            logger.error('Failed to get URL for upload: {}'.format(e))
            raise

        try:
            with open(boxpath) as boxfile:
                upload_start = timeit.default_timer()

                self.context.put(url['upload_path'],
                    data=chunked_file_with_progressbar(boxfile))

                upload_end = timeit.default_timer()
                logger.info('Upload took {:0.2f} seconds'.format(
                    upload_end-upload_start))
        except Exception as e:
            logger.error('Failed to upload box: {}'.format(e))
            raise

    def download(self, targetpath):
        path = self._path('download', **self.keys)
        try:
            response = self.context.get(path, stream=True)
            with open(targetpath, 'wb') as boxfile:
                for chunk in response.iter_content(chunk_size=2**24):
                    if chunk:
                        boxfile.write(chunk)
        except Exception as e:
            logger.error('Failed to download box: {}'.format(e))
            raise


class BoxProviders(Mapping):
    obj_cls = BoxProvider
    obj_key = 'providers'
    id_key = 'name'


class BoxVersion(CRUD):
    path_template = {
        'create': 'api/v1/box/{username}/{name}/versions',
        'read': 'api/v1/box/{username}/{name}/version/{version}',
        'update': 'api/v1/box/{username}/{name}/version/{version}',
        'delete': 'api/v1/box/{username}/{name}/version/{version}',
        'release': 'api/v1/box/{username}/{name}/version/{version}/release',
        'revoke': 'api/v1/box/{username}/{name}/version/{version}/revoke',
    }
    primary_keys = {'username', 'name', 'version'}
    data_keys = {'version', 'description'}
    data_name = 'version'

    @classmethod
    def create(cls, box, version, description=None):
        return super(BoxVersion, cls).create(box.context,
            name=box.keys['name'], username=box.keys['username'],
            version=version, description=description)

    def __init__(self, box, version, description=None):
        super(BoxVersion, self).__init__(box.context,
            name=box.keys['name'], username=box.keys['username'],
            version=version, description=description)
        self.providers = BoxProviders(self)

    def release(self):
        path = self._path('release', **self.keys)
        try:
            self.context.put(path)
        except Exception as e:
            logger.error('Failed to release {}: {}'. format(
                self.__class__.__name__, e))
            raise

    def revoke(self):
        path = self._path('revoke', **self.keys)
        try:
            self.context.put(path)
        except Exception as e:
            logger.error('Failed to release {}: {}'. format(
                self.__class__.__name__, e))
            raise

    def add_provider(self, provider, filename=None, url=None):
        if url and filename:
            raise RuntimeError("filename and url can't be specified together")
        else:
            BoxProvider.create(self, provider)
            boxprovider = BoxProvider(self, provider)

            if url:
                boxprovider.update(url=url)
            elif filename:
                boxprovider.upload(filename)

            return boxprovider


class BoxVersions(Mapping):
    obj_cls = BoxVersion
    obj_key = 'versions'
    id_key = 'version'

    def max(self):
        return max(self, key=lambda v: [int(i) for i in v.split('.')])


class Box(CRUD):
    path_template = {
        'create': 'api/v1/boxes',
        'read': 'api/v1/box/{username}/{name}',
        'update': 'api/v1/box/{username}/{name}',
        'delete': 'api/v1/box/{username}/{name}',
    }
    primary_keys = {'username', 'name'}
    data_keys = primary_keys.union({
        'short_description', 'description', 'is_private'})
    data_name = 'box'

    @classmethod
    def create(cls, context, name, username, short_description=None,
               description=None, is_private=None):
        if not username:
            username = context.username

        return super(Box, cls).create(context,
            name=name, username=username, short_description=short_description,
            description=description, is_private=is_private)

    def __init__(self, context, name, username=None):
        if not username:
            username = context.username
        super(Box, self).__init__(context, name=name, username=username)
        self.versions = BoxVersions(self)

    def add_version(self, version, description=None):
        BoxVersion.create(self, version, description)
        return BoxVersion(self, version)


class Context(object):
    def __init__(self, url, username, token):
        self.base_url = url
        self.username = username
        self.token = token
        self.auth_header = {'X-Atlas-Token': token}
        self.boxes = Boxes(self)

    @staticmethod
    def custom_data_encode(data):
        exprs = []
        ret = []

        def _encode(data, chain=()):
            for key, value in data.items():
                if isinstance(value, dict):
                    _encode(value, tuple(list(chain) + [key]))
                else:
                    exprs.append((tuple(list(chain) + [key]), value))

        _encode(data)

        for var in exprs:
            path, value = var
            keys = ''.join(['[{}]'.format(k) for k in path[1:]])
            var = path[0]
            ret.append('{}{}{}'.format(var, keys, urlencode({'': value})))

        return '&'.join(ret)

    def get(self, path, data=None):
        url = urljoin(self.base_url, path)
        logging.debug('GET: {}, {}'.format(url, data))
        response = requests.get(url, params=data, headers=self.auth_header)
        response.raise_for_status()
        return response.json()

    def post(self, path, data=None):
        url = urljoin(self.base_url, path)
        if isinstance(data, dict):
            data = self.custom_data_encode(data)
        logging.debug('POST: {}, {}'.format(url, data))
        response = requests.post(url, data=data, headers=self.auth_header)
        response.raise_for_status()
        return response.json()

    def put(self, path, data=None):
        url = urljoin(self.base_url, path)
        if isinstance(data, dict):
            data = self.custom_data_encode(data)

        logging.debug('PUT: {}, {}'.format(url, data))
        response = requests.put(url, data=data, headers=self.auth_header)
        response.raise_for_status()

    def delete(self, path):
        url = urljoin(self.base_url, path)
        logging.debug('DELETE: {}'.format(url))
        response = requests.delete(url, headers=self.auth_header)
        response.raise_for_status()

    def add_box(self, name, username=None, short_description=None,
                description=None, is_private=None):
        Box.create(self, name, username, short_description,
                   description, is_private)
        return Box(self, name, username)
