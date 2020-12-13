import datetime
import io
import logging
import re
import zipfile

from . import api
from .exceptions import DocumentNotFound

def now():
    return datetime.datetime.now(datetime.timezone.utc)

class Item:

    DOCUMENT = 'DocumentType'
    FOLDER = 'CollectionType'

    @staticmethod
    def parse_datetime(dt):
        # fromisoformat needs 0, 3, or 6 decimal places for the second, but
        # we can get other numbers from the API.  Since we're not doing anything
        # that time-sensitive, we'll just chop off the fractional seconds.
        dt = re.sub(r'\.\d*', '', dt).replace('Z', '+00:00')
        return datetime.datetime.fromisoformat(dt)

    @classmethod
    def from_metadata(cls, metadata):
        type_ = metadata.get('Type')
        if type_ == cls.DOCUMENT:
            return Document(metadata)
        if type_ == cls.FOLDER:
            return Folder(metadata)
        logging.error(f"Unknown document type: {type_}")
        return None

    def __init__(self, metadata):
        self._metadata = metadata
        self._raw = b''
        self._raw_size = 0
        self._type = None
        self._size = 0

    @property
    def name(self):
        return self._metadata.get('VissibleName')

    @property
    def id(self):
        return self._metadata.get('ID')

    @property
    def parent(self):
        return self._metadata.get('Parent')

    @property
    def mtime(self):
        return self.parse_datetime(self._metadata.get('ModifiedClient'))

    @property
    def virtual(self):
        return False

    def __repr__(self):
        return f'<{self.__class__.__name__} "{self.name}">'

    def refresh_metadata(self, downloadable=True):
        try:
            self._metadata = api.client.get_metadata(self.id, downloadable)
        except DocumentNotFound:
            logging.error(f"Could not update metadata for {self}")

    @property
    def download_url(self):
        if not (self._metadata['BlobURLGet'] and
                self.parse_datetime(self._metadata['BlobURLGetExpires']) > now()):
            self.refresh_metadata(downloadable=True)
        # This could have failed...
        url = self._metadata['BlobURLGet']
        if url and self.parse_datetime(self._metadata['BlobURLGetExpires']) > now():
            return url
        return None

    @property
    def raw(self):
        if not self._raw and self.download_url:
            self._raw = api.client.get_blob(self.download_url)
        return self._raw

    @property
    def raw_size(self):
        if not self._raw_size and self.download_url:
            self._raw_size = api.client.get_blob_size(self.download_url)
        return self._raw_size

    def _get_details(self):
        if not self._type and self.download_url:
            print('Getting details', self)
            self._type, self._size = api.client.get_file_details(self.download_url)
            if self._size is None:
                self._size = self.raw_size
            print('  Got', self._type, self._size)

    @property
    def type(self):
        self._get_details()
        return self._type

    @property
    def size(self):
        self._get_details()
        return self._size


class Document(Item):

    def __init__(self, metadata):
        super().__init__(metadata)
        self._contents = None

    @property
    def contents(self):
        if self.type in (api.FileType.notes, api.FileType.unknown):
            return self.raw

        if self._contents is None:
            zf = zipfile.ZipFile(io.BytesIO(self.raw), 'r')
            for f in zf.filelist:
                if f.filename.endswith(str(self.type)):
                    self._contents = zf.read(f)
                    break
            else:
                self._contents = b'Unable to load file contents'
        return self._contents


class Folder(Item):

    def __init__(self, metadata):
        super().__init__(metadata)
        self.children = []


class VirtualFolder(Folder):

    def __init__(self, name):
        self._name = name
        self.children = []

    @property
    def name(self):
        return self._name

    @property
    def id(self):
        return self._name.lower()

    @property
    def parent(self):
        return None

    @property
    def mtime(self):
        return now()

    @property
    def virtual(self):
        return True
