#!/usr/bin/python

from .base import Context, CRUD, Mapping

import collections
import requests
from urlparse import urljoin
import logging


class CRUD(object):
    path_template = {}
    primary_keys = set()
    data_keys = set()

    @classmethod
    def _path(cls, method, **keys):
        return cls.path_template[method].format(**keys)

    @classmethod
    def _get_keys(cls, **kwargs):
        return {k: v for k, v in kwargs.items() if k in cls.primary_keys}

    @classmethod
    def _prepare_data(cls, **kwargs):
        return {k: v for k, v in kwargs.items() if k in cls.data_keys and v}

    def _refresh(self):
        path = self._path('read', **self.keys)
        self.data = self.context.get(path)

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
            return context.post(path, data)
        except Exception as e:
            logger.error('Failed to create {}: {}'.format(cls.__name__, e))
            raise

        return cls(context, **keys)

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


class BoxVersions(Mapping):
    obj_cls = BoxVersion
    obj_key = 'versions'
    id_key = 'version'

    def max(self):
        return max(self, key=lambda v: [int(i) for i in v.split('.')])


class BoxProviders(Mapping):
    obj_cls = BoxProvider
    obj_key = 'providers'
    id_key = 'name'


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
    data_keys = primary_keys.union({'url'})

    @classmethod
    def create(cls, boxversion, provider, url=None):
        return super(BoxProvider, cls).create(boxversion.context
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
                return self.context.put(url['upload_path'], data=boxfile)
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
        self._path('release', **self.keys)
        try:
            return self.context.put(_path)
        except Exception as e:
            logger.error('Failed to release {}: {}'. format(
                self.__class__.__name__, e))
            raise

    def revoke(self):
        self._path('revoke', **self.keys)
        try:
            return self.context.put(_path)
        except Exception as e:
            logger.error('Failed to release {}: {}'. format(
                self.__class__.__name__, e))
            raise

    def add_provider(self, provider, filename=None, url=None):
        if url and filename:
            raise RuntimeError("filename and url can't be specified together")
        elif url:
            return BoxProvider.create(self, provider, url)
        elif filename:
            boxprovider = BoxProvider.create(self, provider)
            boxprovider.upload(filename)
            return boxprovider
        else:
            raise RuntimeError("filename or url must be specified")


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

    @classmethod
    def create(self, context, name, username, short_description=None,
               description=None, is_private=None):
        return super(Box, self).create(context,
            name=name, username=username, short_description=short_description,
            description=description, is_private=is_private)

    def __init__(self, context, name, username):
        super(Box, self).__init__(context, name=name, username=username)
        self.versions = BoxVersions(self)

    def add_version(self, version, description=None):
        return BoxVersion.create(self, version, description)


class Context(object):
    def __init__(self, url, username, token):
        self.base_url = url
        self.username = username
        self.token = token
        self.auth_header = {'X-Atlas-Token': token}
        self.boxes = Boxes(self)

    def get(self, path, data=None):
        url = urljoin(self.base_url, path)
        logging.debug('GET: {}, {}'.format(url, data))
        return requests.get(url, params=data, headers=self.auth_header).json()

    def post(self, path, data=None):
        url = urljoin(self.base_url, path)
        logging.debug('POST: {}, {}'.format(url, data))
        return requests.post(url, data=data, headers=self.auth_header).json()

    def put(self, path, data=None):
        url = urljoin(self.base_url, path)
        logging.debug('PUT: {}, {}'.format(url, data))
        return requests.put(url, data=data, headers=self.auth_header).json()

    def delete(self, path):
        url = urljoin(self.base_url, path)
        logging.debug('DELETE: {}'.format(url))
        return requests.delete(url, headers=self.auth_header).json()

    def add_box(self, name, username=None, short_description=None,
                description=None, is_private=None):
        return Box.create(self, name, username, short_description,
                          description, is_private)
