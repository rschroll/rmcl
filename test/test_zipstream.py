import io
import zipfile

import pytest

from rmapy import zipstream

FILENAME = 'filename'
FILE_CONTENTS = b'contents ' * 100

def make_zipfile(file_data=[(FILENAME, FILE_CONTENTS)], algo=zipfile.ZIP_STORED):
    bio = io.BytesIO()
    zf = zipfile.ZipFile(bio, 'w', algo)
    for fn, data in file_data:
        zf.writestr(fn, data)
    zf.close()
    bio.seek(0)
    return bio

@pytest.mark.parametrize('algo', [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED,
                                  zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA])
def test_compression_algos(algo):
    fs = make_zipfile(algo=algo)
    entry = zipstream.ZipEntry.from_stream(fs)
    assert entry.filename == FILENAME.encode('utf-8')
    assert entry.contents == FILE_CONTENTS

def test_multiple_files():
    file_data = [
        ('file1', b'contents1'),
        ('file2', b'contents2')
    ]

    fs = make_zipfile(file_data)
    for fn, data in file_data:
        entry = zipstream.ZipEntry.from_stream(fs)
        assert entry.filename == fn.encode('utf-8')
        assert entry.contents == data

def test_end_stream():
    fs = make_zipfile()
    zipstream.ZipEntry.from_stream(fs)
    with pytest.raises(zipstream.ZipError) as excinfo:
        zipstream.ZipEntry.from_stream(fs)
    assert 'Invalid signature' in str(excinfo.value)

def test_truncated_stream():
    fs = make_zipfile()
    fs.truncate(10)
    entry = zipstream.ZipEntry.from_stream(fs)
    assert entry.filename == FILENAME.encode('utf-8')
    assert entry.contents == None
