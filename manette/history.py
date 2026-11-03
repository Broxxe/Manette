"""Bounded, local operation journal. No command is replayed from this database."""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from gi.repository import GLib

MAX_OUTPUT = 128 * 1024
MAX_ENTRIES = 500


def tail(text, limit=MAX_OUTPUT):
    return text.encode('utf-8')[-limit:].decode('utf-8', 'ignore') if limit > 0 else ''


def path():
    return Path(GLib.get_user_state_dir()) / 'manette' / 'operations.sqlite3'


@contextmanager
def _connect():
    file = path()
    file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Create privately before SQLite opens it (rather than relying on the umask).
    file.touch(mode=0o600, exist_ok=True)
    connection = sqlite3.connect(file, timeout=3)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('''CREATE TABLE IF NOT EXISTS operations (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, command TEXT NOT NULL,
            started TEXT NOT NULL, finished TEXT, status TEXT NOT NULL,
            code INTEGER, output TEXT NOT NULL DEFAULT '')''')
        with connection:
            yield connection
    finally:
        connection.close()


def start(title, command=''):
    with _connect() as connection:
        cursor = connection.execute(
            'INSERT INTO operations(title, command, started, status) VALUES (?, ?, ?, ?)',
            (title, command, datetime.now(timezone.utc).isoformat(timespec='seconds'), 'running'))
        connection.execute('DELETE FROM operations WHERE id NOT IN '
                           '(SELECT id FROM operations ORDER BY id DESC LIMIT ?)', (MAX_ENTRIES,))
        return cursor.lastrowid


def finish(ident, code, output='', status=None):
    with _connect() as connection:
        connection.execute('UPDATE operations SET finished=?, status=?, code=?, output=? WHERE id=?',
            (datetime.now(timezone.utc).isoformat(timespec='seconds'),
             status or ('success' if code == 0 else 'stopped' if code == -1 else 'failed'),
             code, tail(output), ident))


def record(title, code=0, output='', command='', status=None):
    ident = start(title, command)
    finish(ident, code, output, status)
    return ident


def recover():
    # A closed/crashed Manette cannot determine the outcome of its old processes.
    with _connect() as connection:
        connection.execute("UPDATE operations SET status='unknown' WHERE status='running'")


def entries():
    with _connect() as connection:
        return [dict(row) for row in connection.execute('SELECT * FROM operations ORDER BY id DESC')]


def clear():
    with _connect() as connection:
        connection.execute('PRAGMA secure_delete=ON')
        connection.execute("DELETE FROM operations WHERE status != 'running'")
    with _connect() as connection:
        connection.execute('VACUUM')
