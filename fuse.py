import argparse
import enum
import errno
import os
import stat

import bidict
import pyfuse3
import trio

from rmapy import client
from rmapy.items import Document, Folder

class FSMode(enum.Enum):
    meta = 'meta'
    raw = 'raw'
    orig = 'orig'

    def __str__(self):
        return self.name

class RmApiFS(pyfuse3.Operations):

    def __init__(self, mode):
        super().__init__()
        self._next_inode = pyfuse3.ROOT_INODE
        self.inode_map = bidict.bidict()
        self.inode_map[self.next_inode()] = ''
        self.mode = mode

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

    def filename(self, item):
        base = item.name.encode('utf-8')
        if isinstance(item, Folder):
            return base

        if self.mode == FSMode.raw:
            return base + b'.zip'
        if self.mode == FSMode.orig:
            return base + b'.' + str(item.type).encode('utf-8')
        return base

    async def lookup(self, inode_p, name, ctx=None):
        folder = client.get_by_id(self.get_id(inode_p))
        if name == '.':
            inode = inode_p
        elif name == '..':
            if folder.parent is None:
                raise pyfuse3.FUSEError(errno.ENOENT)
            inode = self.get_inode(folder.parent)
        else:
            for f in folder.children:
                if f.name == name:
                    inode = self.get_inode(f)
                    break
            else:
                raise pyfuse3.FUSEError(errno.ENOENT)

        return await self.getattr(inode, ctx)

    async def getattr(self, inode, ctx=None):
        item = client.get_by_id(self.get_id(inode))
        entry = pyfuse3.EntryAttributes()
        if isinstance(item, Document):
            entry.st_mode = (stat.S_IFREG | 0o444)  # TODO: Permissions?
            if self.mode == FSMode.raw:
                entry.st_size = item.raw_size
            elif self.mode == FSMode.orig:
                entry.st_size = item.size
            else:
                entry.st_size = 0
        elif isinstance(item, Folder):
            entry.st_mode = (stat.S_IFDIR | 0o555)
            entry.st_size = 0

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
        item = client.get_by_id(self.get_id(inode))
        for i, c in enumerate(item.children[start_id:]):
            pyfuse3.readdir_reply(token, self.filename(c),
                                  await self.getattr(self.get_inode(c.id)),
                                  start_id + i + 1)
        # TODO: include . and ..

    async def open(self, inode, flags, ctx):
        if inode not in self.inode_map:
            raise pyfuse3.FUSEError(errno.ENOENT)
        if flags & os.O_RDWR or flags & os.O_WRONLY:  # TODO: Fix permissions
            raise pyfulse3.FUSEError(errno.EPERM)
        return pyfuse3.FileInfo(fh=inode, direct_io=True)  # direct_io means our size doesn't have to be correct

    async def read(self, fh, start, size):
        item = client.get_by_id(self.get_id(fh))
        if self.mode == FSMode.meta:
            contents = f'{item._metadata!r}\n'.encode('utf-8')
        elif self.mode == FSMode.raw:
            contents = item.raw
        elif self.mode == FSMode.orig:
            contents = item.contents
        return contents[start:start+size]

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
