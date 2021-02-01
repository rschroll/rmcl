# Copyright 2020-2021 Robert Schroll
# This file is part of rmcl and is distributed under the MIT license.

import io
import json
import logging
import uuid
import zipfile

import trio
try:
    from rmrl import render, sources
except ImportError:
    render = None

from . import api
from .const import ROOT_ID, TRASH_ID, FileType
from . import datacache
from . import documentcache
from .exceptions import DocumentNotFound, VirtualItemError
from .utils import now, parse_datetime

def with_lock(func):
    async def decorated(self, *args, **kw):
        if self._lock.statistics().owner == trio.lowlevel.current_task():
            return await func(self, *args, **kw)

        async with self._lock:
            return await func(self, *args, **kw)

    return decorated


class Item:

    DOCUMENT = 'DocumentType'
    FOLDER = 'CollectionType'

    @staticmethod
    async def get_by_id(id_):
        return await (await api.get_client()).get_by_id(id_)

    @staticmethod
    async def invalidate_cache():
        (await api.get_client()).refresh_deadline = None

    @classmethod
    def from_metadata(cls, metadata):
        type_ = metadata.get('Type')
        if type_ == cls.DOCUMENT:
            return Document(metadata)
        if type_ == cls.FOLDER:
            return Folder(metadata)
        logging.error(f"Unknown document type: {type_}")
        return None

    @classmethod
    def new(cls, name, parent_id):
        if issubclass(cls, Document):
            type_ = cls.DOCUMENT
        elif issubclass(cls, Folder):
            type_ = cls.FOLDER
        else:
            logging.error(f"Cannot create a new item of class {cls}")
            return None

        metadata = {
            'VissibleName': name,
            'ID': str(uuid.uuid4()),
            'Version': 0,
            'Parent': parent_id,
            'Type': type_
        }
        return cls(metadata)

    def __init__(self, metadata):
        self._metadata = metadata
        self._raw_size = datacache.get_property(self.id, self.version, 'raw_size') or 0
        self._size = datacache.get_property(self.id, self.version, 'size') or 0
        try:
            self._type = FileType[datacache.get_property(self.id, self.version, 'type')]
        except KeyError:
            self._type = None
        self._lock = trio.Lock()

    @property
    def name(self):
        return self._metadata.get('VissibleName')

    @name.setter
    def name(self, value):
        self._metadata['VissibleName'] = value

    @property
    def id(self):
        return self._metadata.get('ID')

    @property
    def version(self):
        return self._metadata.get('Version')

    @property
    def parent(self):
        return self._metadata.get('Parent')

    @parent.setter
    def parent(self, value):
        self._metadata['Parent'] = value

    @property
    def mtime(self):
        return parse_datetime(self._metadata.get('ModifiedClient'))

    @property
    def virtual(self):
        return False

    def __repr__(self):
        return f'<{self.__class__.__name__} "{self.name}">'

    async def refresh_metadata(self, downloadable=True):
        try:
            self._metadata = await (await api.get_client()).get_metadata(self.id, downloadable)
        except DocumentNotFound:
            logging.error(f"Could not update metadata for {self}")

    @with_lock
    async def download_url(self):
        if not (self._metadata['BlobURLGet'] and
                parse_datetime(self._metadata['BlobURLGetExpires']) > now()):
            await self.refresh_metadata(downloadable=True)
        # This could have failed...
        url = self._metadata['BlobURLGet']
        if url and parse_datetime(self._metadata['BlobURLGetExpires']) > now():
            return url
        return None

    @with_lock
    async def raw(self):
        contents = documentcache.get_document(self.id, self.version, 'raw')
        if not contents and await self.download_url():
            contents = await (await api.get_client()).get_blob(await self.download_url())
            documentcache.set_document(self.id, self.version, 'raw', contents)
        return contents

    @with_lock
    async def raw_size(self):
        if not self._raw_size and await self.download_url():
            self._raw_size = await (await api.get_client()).get_blob_size(await self.download_url())
            datacache.set_property(self.id, self.version, 'raw_size', self._raw_size)
        return self._raw_size

    @with_lock
    async def _get_details(self):
        if not self._type and await self.download_url():
            print('Getting details', self)
            self._type, self._size = await (await api.get_client()).get_file_details(await self.download_url())
            if self._size is None:
                self._size = await self.raw_size()
            datacache.set_property(self.id, self.version, 'size', self._size)
            if self._type != FileType.unknown:
                # Try again the next time we start up.
                datacache.set_property(self.id, self.version, 'type', str(self._type))
            print('  Got', self._type, self._size)

    async def type(self):
        await self._get_details()
        return self._type

    async def size(self):
        await self._get_details()
        return self._size

    @with_lock
    async def update_metadata(self):
        if self.virtual:
            raise VirtualItemError('Cannot update virtual items')
        await (await api.get_client()).update_metadata(self)

    @with_lock
    async def delete(self):
        if self.virtual:
            raise VirtualItemError('Cannot delete virtual items')

        client = await api.get_client()
        folder = self
        while folder.parent:
            folder = await client.get_by_id(folder.parent)
            if folder.id == TRASH_ID:
                return await client.delete(self)
        self.parent = TRASH_ID
        await client.update_metadata(self)

    @with_lock
    async def upload_raw(self, new_contents):
        if self.virtual:
            raise VirtualItemError('Cannot update virtual items')
        await (await api.get_client()).upload(self, new_contents)


class Document(Item):

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self._annotated_size = datacache.get_property(self.id, self.version, 'annotated_size')

    async def contents(self):
        if await self.type() in (FileType.notes, FileType.unknown):
            return await self.raw()

        contents = documentcache.get_document(self.id, self.version, 'orig')
        if contents is None:
            zf = zipfile.ZipFile(io.BytesIO(await self.raw()), 'r')
            for f in zf.filelist:
                if f.filename.endswith(str(await self.type())):
                    contents = zf.read(f)
                    break
            else:
                contents = b'Unable to load file contents'
            print(len(contents))
            documentcache.set_document(self.id, self.version, 'orig', contents)
        return contents

    async def upload(self, new_contents, type_):
        if type_ not in (FileType.pdf, FileType.epub):
            raise TypeError(f"Cannot upload file of type {type_}")

        content = {
            'extraMetadata': {},
            'fileType': str(type_),
            'lastOpenedPage': 0,
            'lineHeight': -1,
            'margins': 100,
            'pageCount': 0,
            'textScale': 1,
            'transform': {},
        }

        f = io.BytesIO()
        with zipfile.ZipFile(f, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f'{self.id}.pagedata','')
            zf.writestr(f'{self.id}.content', json.dumps(content))
            zf.writestr(f'{self.id}.{type_}', new_contents.read())
        f.seek(0)

        return await self.upload_raw(f)

    async def annotated(self, **render_kw):
        if render is None:
            raise ImportError("rmrl must be installed to get annotated documents")

        contents = documentcache.get_document(self.id, self.version, 'annot')
        if contents is None:
            zf = zipfile.ZipFile(io.BytesIO(await self.raw()), 'r')
            # run_sync doesn't accept keyword arguments to be passed to the sync
            # function, so we'll assemble to function to call out here.
            render_func = lambda: render(sources.ZipSource(zf), **render_kw)
            contents = (await trio.to_thread.run_sync(render_func)).read()
            documentcache.set_document(self.id, self.version, 'annot', contents)
            self._annotated_size = len(contents)
            datacache.set_property(self.id, self.version, 'annotated_size', self._annotated_size)
        return contents

    async def annotated_size(self):
        if self._annotated_size is not None:
            return self._annotated_size
        return await self.size()


class Folder(Item):

    def __init__(self, metadata):
        super().__init__(metadata)
        self.children = []

    async def upload(self):
        f = io.BytesIO()
        with zipfile.ZipFile(f, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f'{self.id}.content', '')
        f.seek(0)

        return await self.upload_raw(f)


class VirtualFolder(Folder):

    def __init__(self, name, id_, parent_id=None):
        self._name = name
        self._id = id_
        self._parent = parent_id
        self.children = []

    @property
    def name(self):
        return self._name

    @property
    def id(self):
        return self._id

    @property
    def parent(self):
        return self._parent

    @property
    def mtime(self):
        return now()

    @property
    def virtual(self):
        return True
