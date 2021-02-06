# rmcl: reMarkable Cloud Library

rmcl is a Python library for interacting with the reMarkable cloud.  It
supports a file-tree view onto your files, exposes metadata, and gives
access to the original PDF or EPUB documents.  If
[rmrl](https://github.com/rschroll/rmrl) is installed, it can also
produce PDF versions of any type of document with your annotations
included.  rmcl can create, update, and delete items from the
reMarkable cloud.

## Quick Demo

As a taste, this code will list all of the files and their types in the
root directory of your reMarkable cloud.
```python
from rmcl import Item, Document, Folder
import trio

async def list_files():
    root = await Item.get_by_id('')  # The root folder has ID of empty string
    for child in root.children:
        if isinstance(child, Folder):
            print(f"{child.name}: folder")
        elif isinstance(child, Document):  # The only other possibility
            print(f"{child.name}: {await child.type()}")

trio.run(list_files)
```

## Installation

rmcl requires Python 3.7 or later.  If that's installed, the easiest
installation is to do a
```bash
pip install rmcl
```
Alternatively, you may clone this repository.
[Poetry](https://python-poetry.org/) is used for development, so once
that is installed you can run
```bash
poetry install
```
to get a virtual environment all set up.

rmcl is asynchronous, and must be used with the
[trio](https://trio.readthedocs.io/en/stable/) async library.

## Features

### Asynchronous

rmcl is asynchronous at its core.  This keeps it from blocking during the
many HTTP transactions it uses.  Most methods are `async`, and therefore
must be called with the `await` keyword.  rmcl is designed to work with
the [trio](https://trio.readthedocs.io/en/stable/) async library.

### Synchronous Option

Asynchronous code can be overkill for simple scripts, so rmcl offers
synchronous versions of all of its async functions.  These functions
have a suffix of `'_s'` in their names.  This means that the above
example could be written
```python
def list_files_sync():
    root = Item.get_by_id_s('')
    for child in root.children:
        if isinstance(child, Folder):
            print(f"{child.name}: folder")
        elif isinstance(child, Document):
            print(f"{child.name}: {child.type_s()}")
```
Note that these synchronous functions are still calling the asynchronous
low-level code.  They may fail if called within another asynchronous
framework.

### Object Oriented

The main interface to rmcl is the `Item` class and its two subclasses,
`Folder` and `Document`.  The reMarkable cloud gives each item an ID.
If the ID of an Item is known, it can be retrieved with the
`Item.get_by_id()` static method.  New `Folder`s and `Document`s can be
made with the `.new()` class method, which expects as arguments the item's
name and parent ID.

While the cloud API presents a flat directory structure, rmcl assembles
these objects into a file tree.  Every `Folder` has a `.children` attribute,
a list of the `Item`s within it.  Each `Item` has a `.parent` property,
which gives the ID of its parent.  (The ID is given instead of the parent to avoid circular references.)  The parent object of `item` may be looked up
with `await Item.get_by_id(item.parent)`.

Two "virtual" folders are provided.  The root folder (ID = `''`) contains
all `Item`s with no explicit parent.  The trash folder (ID = `'trash'`)
contains all `Item`s marked as trashed.

Various metadata are exposed as properties: `.name`, `.id`, `.version`,
`.parent`, and `.mtime`, for modification time.  The `.name` and `.parent`
properties can be modified, which updates the underlying metadata.  Such
changes can be sent to the cloud with the `.update_metadata()` method.

The contents of `Document`s can be retrieved in several ways.  The
`.raw()` method gets the zip file that the reMarkable cloud API uses
to transfer documents.  The `.contents()` method gets the original PDF
or EPUB file associated with a `Document`.  If
[rmrl](https://github.com/rschroll/rmrl) is installed, the `.annotated()`
method yields a PDF file with the user's annotations.  All three methods
return a file-like object, but the exact type is not guaranteed and may
vary in the future.  The same object may be returned from multiple calls
to a given method; the user is responsible for coordinating `read`s and
`seek`s to avoid contention.

New `Item`s or existing `Document`s with new contents may be uploaded to
the cloud with `.upload()` method.

### Smart Updates

rmcl keeps a list of all documents in the reMarkable cloud, so that it
doesn't need to query the API for each bit of information.  To ensure
this list is up to date, it automatically refreshes itself when you use
`Item.get_by_id()` more than five minutes after the last refresh.  You
can also trigger this behavior by calling `rmcl.invalidate_cache()`
before `Item.get_by_id()`.

rmcl only updates objects that have a new version, so existing objects
remain valid.  Nonetheless, it is better to call `Item.get_by_id()`
often, instead of keeping your own list of `Item`s.

### Caching Expensive Operations

Some of this information, like document type and size, require several
round trips to calculate.  rmcl stores these values locally, so they do
not need to be recalculated every time.  They are stored in a persistent
database, so this information is not lost when the process stops.  The
database stores this information by version, so it knows when it must be
recalculated.

rmcl does some simple caching of document contents after it is downloaded.
It currently only keeps the most recent contents, but we hope to build a
more sophisticated caching system soon.

### Handles Authentication

The reMarkable cloud requires two tokens: The *device token* identifies
your device and needs only to be set once.  The *user token* is used on
most requests, and should be updated occasionally.  rmcl automatically
renews the user token each time it is run.

Getting the device token requires user interaction the first time a
program is run.  If rmcl detects that it is being run interactively, it
will print instructions and prompt to user to input a new device token.
Otherwise, it will throw a `rmcl.exceptions.AuthError`.  You must call
`register_device(code)` with the code provided obtained from
https://my.remarkable.com/connect/desktop.  Once obtained, the device
token is stored for future use.

## Comparison with rMapy

rmcl started as a fork of [rMapy](https://github.com/subutux/rmapy).
As we started moving in a rather different direction, we decided it
would be better to make it into its own project.  At this point, only
some of the low-level API code from rMapy remains.

To help users decide which library best fits their needs, here are the
major differences:
- rmcl is asynchronous, while rMapy is synchonous.  This means that
  rmcl will not block while making HTTP requests to the reMarkable API.
  rmcl's synchronous functions will block, much like rMapy.
- rmcl has a simpler object structure, mostly focused around `Item` and
  its subclasses `Document` and `Folder`.  rMapy has similar objects
  (`Meta`, `Document`, and `Folder`), but it also has a `Client` and
  `Collection` singleton objects, and operations like getting documents
  or listing directories are provided by these singletons.
- rmcl abstracts away some details of the reMarkable cloud API, while
  rMapy provides a more direct mapping of the API into Python.  For
  instance, rMapy items have a `.VissibleName` _[sic]_ property, because
  that's what the API provides.  rmcl turns this into a `.name` property.
  In rmcl, `Folder`s have a list of children, but in rMapy, the children
  must be looked up via the `Collection` singleton.  (The API provides
  a flat file list.)
- rMapy is more complete than rmcl.  rMapy exposes all metadata as
  properties, while rmcl only exposes some metadata items.  rMapy provides
  an object model for the zip files provided by the API, while rmcl just
  exposes the zip files themselves.
- rMapy has [better documentation](https://rmapy.readthedocs.io/en/latest/)
  than rmcl.  (But we're working on it!)

## Trademarks

reMarkable(R) is a registered trademark of reMarkable AS. rmrl is not
affiliated with, or endorsed by, reMarkable AS. The use of "reMarkable" in
this work refers to the company’s e-paper tablet product(s).

## Copyright

Copyright 2019 Stijn Van Campenhout

Copyright 2020-2021 Robert Schroll

rmcl is released under the MIT license.  See LICENSE.txt for details.
