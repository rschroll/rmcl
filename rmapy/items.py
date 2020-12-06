import datetime
import logging
import re

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


class Document(Item):

    def get_contents(self):
        ...


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
        return datetime.datetime.now(datetime.timezone.utc)

    @property
    def virtual(self):
        return True
