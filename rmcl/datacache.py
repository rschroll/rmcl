# Copyright 2020-2021 Robert Schroll
# This file is part of rmcl and is distributed under the MIT license.

import sqlite3

from xdg import xdg_cache_home

CACHE_FILE = xdg_cache_home() / 'rmcl' / 'filedata.db'

def _fix_old_cache_dir():
    # 2/14/2021 -- We had been using the 'rmfuse' cache directory since
    # early development.  Let's use rmcl instead.  But we'll move the
    # existing DB over, if it exists and the new one doesn't.
    old_cache_file = xdg_cache_home() / 'rmfuse' / 'filedata.db'
    if old_cache_file.exists() and not CACHE_FILE.exists():
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        old_cache_file.rename(CACHE_FILE)
_fix_old_cache_dir()

_conn = None
def _get_conn():
    global _conn
    if _conn is not None:
        return _conn

    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(CACHE_FILE)
    c = _conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS filedata
                 (id TEXT, version INTEGER, property TEXT, value BLOB,
                  UNIQUE(id, version, property))''')
    _conn.commit()
    return _conn

def get_property(id_, version, property_):
    conn = _get_conn()
    c = conn.cursor()
    c.execute('SELECT value FROM filedata WHERE id=? AND version=? and property=?',
              (id_, version, property_))
    res = c.fetchone()
    if res:
        return res[0]
    return None

def set_property(id_, version, property_, value):
    conn = _get_conn()
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO filedata VALUES(?, ?, ?, ?)',
              (id_, version, property_, value))
    conn.commit()
