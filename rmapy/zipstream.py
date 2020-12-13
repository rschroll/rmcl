from binascii import crc32
from dataclasses import dataclass
from typing import Optional

# Cribbed from Python's zipfile: https://github.com/python/cpython/blob/master/Lib/zipfile.py
decompressors = {
    0:  lambda x: x,
}
try:
    import zlib
except ImportError:
    pass
else:
    decompressors[8] = lambda x: zlib.decompress(x, wbits=-15)
try:
    import bz2
except ImportError:
    pass
else:
    decompressors[12] = bz2.decompress
try:
    import lzma
except ImportError:
    pass
else:
    def lzma_decompress(data):
        psize = int.from_bytes(data[2:4], 'little')
        filters = lzma._decode_filter_properties(lzma.FILTER_LZMA1, data[4:4+psize])
        return lzma.decompress(data[4+psize:], lzma.FORMAT_RAW, filters=[filters])
    decompressors[14] = lzma_decompress


class ZipError(Exception):
    pass

# Useful reference: https://users.cs.jmu.edu/buchhofp/forensics/formats/pkzip.html
@dataclass
class ZipEntry:
    version: int
    flags: int
    compression: int
    datetime_info: bytes
    crc: bytes
    compressed_size: int
    uncompressed_size: int
    filename_size: int
    extra_field_size: int
    filename: bytes
    extra_field: bytes
    contents: Optional[bytes]

    @classmethod
    def from_stream(cls, stream):

        def read_int(nbytes):
            return int.from_bytes(stream.read(nbytes), 'little')

        signature = stream.read(4)
        if not signature:  # Stream is empty
            return None
        if signature != b'\x50\x4b\x03\x04':
            raise ZipError("Invalid signature")

        version = read_int(2)
        flags = read_int(2)
        compression = read_int(2)
        datetime_info = stream.read(4)
        crc = read_int(4)

        compressed_size = read_int(4)
        uncompressed_size = read_int(4)
        filename_size = read_int(2)
        extra_field_size = read_int(2)

        filename = stream.read(filename_size)
        extra_field = stream.read(extra_field_size)

        compressed = stream.read(compressed_size)
        contents = None
        if len(compressed) == compressed_size:
            decompressor = decompressors.get(compression)
            if not decompressor:
                raise ZipError(f"Unsupported compression format: {compression}")
            contents = decompressor(compressed)
            if crc32(contents) != crc:
                raise ZipError("Failed checksum")

        return cls(version, flags, compression, datetime_info, crc, compressed_size,
                   uncompressed_size, filename_size, extra_field_size, filename,
                   extra_field, contents)
