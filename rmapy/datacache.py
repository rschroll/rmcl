import sqlite3

from xdg import xdg_cache_home

CACHE_DIR = xdg_cache_home() / 'rmfuse'

_conn = None
def _get_conn():
    global _conn
    if _conn is not None:
        return _conn

    CACHE_DIR.mkdir(exist_ok=True)
    _conn = sqlite3.connect(CACHE_DIR / 'filedata.db')
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
