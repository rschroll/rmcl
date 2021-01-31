# Copyright 2020-2021 Robert Schroll
# This file is part of rmcl and is distributed under the MIT license.

from dataclasses import dataclass
import struct
from typing import Optional

FIXED_HEADER_FMT = '<HHHH4sLLLHHHH2s4sL'

def unpack(fmt, stream):
    buffer = stream.read(struct.calcsize(fmt))
    return struct.unpack(fmt, buffer)

# Useful reference: https://users.cs.jmu.edu/buchhofp/forensics/formats/pkzip.html
@dataclass
class ZipHeader:
    version_made: int
    version_read: int
    flags: int
    compression: int
    datetime_info: bytes
    crc: int
    compressed_size: int
    uncompressed_size: int
    filename_length: int
    extra_field_length: int
    file_comment_length: int
    disk_number: int
    internal_attr: bytes
    external_attr: bytes
    header_offset: int

    filename: Optional[bytes] = None
    extra_field: Optional[bytes] = None
    file_comment: Optional[bytes] = None

    @classmethod
    def from_stream(cls, stream):
        signature = stream.read(4)
        if signature != b'\x50\x4b\x01\02':
            return None

        obj = cls(*unpack(FIXED_HEADER_FMT, stream))
        obj.filename = stream.read(obj.filename_length)
        obj.extra_field = stream.read(obj.extra_field_length)
        obj.file_comment = stream.read(obj.file_comment_length)
        return obj
