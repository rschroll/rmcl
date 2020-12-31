import argparse
import enum
import errno
import os
import stat

import bidict
import pyfuse3
import trio

from rmapy.api import get_client
from rmapy.items import Document, Folder
from rmapy.utils import now

class FSMode(enum.Enum):
    meta = 'meta'
    raw = 'raw'
    orig = 'orig'

    def __str__(self):
        return self.name


class ModeFile():

    def __init__(self, fs):
        self._fs = fs
        self._metadata = FSMode.meta  # For reading from file in metadata mode

        self.name = '.mode'
        self.id = 'MODE_ID'
        self.parent = ''
        self.virtual = True

    def __repr__(self):
        return f'<{self.__class__.__name__} "{self.name}">'

    @property
    def mtime(self):
        return now()

    async def raw(self):
        return f'{self._fs.mode}\n'.encode('utf-8')

    async def raw_size(self):
        return len(await self.raw())

    async def contents(self):
        return await self.raw()

    async def size(self):
        return len(await self.contents())


class RmApiFS(pyfuse3.Operations):

    def __init__(self, mode):
        super().__init__()
        self._next_inode = pyfuse3.ROOT_INODE
        self.inode_map = bidict.bidict()
        self.inode_map[self.next_inode()] = ''
        self.mode = mode
        self.mode_file = ModeFile(self)
        self.inode_map[self.next_inode()] = self.mode_file.id

    def next_inode(self):
        value = self._next_inode
        self._next_inode += 1
        return value

    def get_id(self, inode):
        return self.inode_map[inode]

    def get_inode(self, id_):
        if id_ not in self.inode_map.inverse:
            self.inode_map[self.next_inode()] = id_
        return self.inode_map.inverse[id_]

    async def get_by_id(self, id_):
        if id_ == self.mode_file.id:
            return self.mode_file
        return await (await get_client()).get_by_id(id_)

    async def filename(self, item, pitem):
        if item == pitem:
            return b'.'
        if pitem.parent == item.id:
            return b'..'

        base = item.name.encode('utf-8')
        if isinstance(item, (Folder, ModeFile)):
            return base

        if self.mode == FSMode.raw:
            return base + b'.zip'
        if self.mode == FSMode.orig:
            return base + b'.' + str(await item.type()).encode('utf-8')
        return base

    async def lookup(self, inode_p, name, ctx=None):
        folder = await self.get_by_id(self.get_id(inode_p))
        if name == '.':
            inode = inode_p
        elif name == '..':
            if folder.parent is None:
                raise pyfuse3.FUSEError(errno.ENOENT)
            inode = self.get_inode(folder.parent)
        elif name == self.mode_file.name:
            inode = self.get_inode(self.mode_file.id)
        else:
            for f in folder.children:
                if f.name == name:
                    inode = self.get_inode(f)
                    break
            else:
                raise pyfuse3.FUSEError(errno.ENOENT)

        return await self.getattr(inode, ctx)

    async def getattr(self, inode, ctx=None):
        item = await self.get_by_id(self.get_id(inode))
        entry = pyfuse3.EntryAttributes()
        if isinstance(item, Document):
            entry.st_mode = (stat.S_IFREG | 0o444)  # TODO: Permissions?
            if self.mode == FSMode.raw:
                entry.st_size = await item.raw_size()
            elif self.mode == FSMode.orig:
                entry.st_size = await item.size()
            else:
                entry.st_size = 0
        elif isinstance(item, Folder):
            entry.st_mode = (stat.S_IFDIR | 0o555)
            entry.st_size = 0
        elif isinstance(item, ModeFile):
            entry.st_mode = (stat.S_IFREG | 0o644)
            entry.st_size = await item.size()

        stamp = int(item.mtime.timestamp() * 1e9)
        entry.st_atime_ns = stamp
        entry.st_ctime_ns = stamp
        entry.st_mtime_ns = stamp
        entry.st_gid = os.getgid()
        entry.st_uid = os.getuid()
        entry.st_ino = inode

        return entry

    async def readlink(self, inode, ctx):
        return NotImplemented

    async def opendir(self, inode, ctx):
        return inode

    async def readdir(self, inode, start_id, token):
        item = await self.get_by_id(self.get_id(inode))
        direntries = [item]
        if item.parent is not None:
            direntries.append(await self.get_by_id(item.parent))
        if item.name == '':
            direntries.append(self.mode_file)
        direntries.extend(item.children)
        for i, c in enumerate(direntries[start_id:]):
            pyfuse3.readdir_reply(token, await self.filename(c, item),
                                  await self.getattr(self.get_inode(c.id)),
                                  start_id + i + 1)

    async def open(self, inode, flags, ctx):
        if inode not in self.inode_map:
            raise pyfuse3.FUSEError(errno.ENOENT)
        if (flags & os.O_RDWR or flags & os.O_WRONLY) and self.get_id(inode) != self.mode_file.id:
            raise pyfuse3.FUSEError(errno.EPERM)
        return pyfuse3.FileInfo(fh=inode, direct_io=True)  # direct_io means our size doesn't have to be correct

    async def read(self, fh, start, size):
        item = await self.get_by_id(self.get_id(fh))
        if self.mode == FSMode.meta:
            contents = f'{item._metadata!r}\n'.encode('utf-8')
        elif self.mode == FSMode.raw:
            contents = await item.raw()
        elif self.mode == FSMode.orig:
            contents = await item.contents()
        return contents[start:start+size]

    async def write(self, fh, offset, buf):
        if self.get_id(fh) != self.mode_file.id:
            raise pyfuse3.FUSEError(errno.EPERM)

        command = buf.decode('utf-8').strip().lower()
        if command == 'refresh':
            (await get_client()).refresh_deadline = None
            return len(buf)

        try:
            self.mode = FSMode[command]
        except KeyError:
            raise pyfuse3.FUSEError(errno.EINVAL)  # Invalid argument
        return len(buf)

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('mountpoint', type=str, help="Mount point of filesystem")
    parser.add_argument('-d', '--debug', action='store_true', default=False,
                        help="Enable debugging output")
    parser.add_argument('-m', '--mode', type=FSMode, choices=list(FSMode),
                        default=FSMode.raw, help="Type of files to mount")
    return parser.parse_args()

def main(options):
    fs = RmApiFS(options.mode)
    fuse_options = set(pyfuse3.default_options)
    fuse_options.add('fsname=rmapi')
    if options.debug:
        fuse_options.add('debug')
    pyfuse3.init(fs, options.mountpoint, fuse_options)
    try:
        trio.run(pyfuse3.main)
    finally:
        pyfuse3.close()

if __name__ == '__main__':
    main(parse_args())
