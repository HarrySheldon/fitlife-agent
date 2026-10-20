from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock, RLock

_WRITE_LOCKS: dict[str, RLock] = {}
_WRITE_LOCKS_GUARD = Lock()


def write_lock_for(path: Path | str) -> RLock:
    """One writer per database file, inside this process.

    SQLite serializes writers itself, but only when every writer can take the
    file lock. On this platform a second connection opening the WAL
    shared-memory file while the first is writing fails with "attempt to write a
    readonly database", and that connection stays unusable. Serializing the write
    transaction — including opening and closing its connection — removes the
    contention instead of retrying against it.

    Reads are unaffected: they never take this lock.
    """
    key = str(Path(path).resolve())
    with _WRITE_LOCKS_GUARD:
        lock = _WRITE_LOCKS.get(key)
        if lock is None:
            lock = RLock()
            _WRITE_LOCKS[key] = lock
        return lock


_WAL_SETUP_MAX_ATTEMPTS = 3
_WAL_SETUP_RETRY_DELAY_SECONDS = 0.01
_BEGIN_MAX_ATTEMPTS = 10
_BEGIN_RETRY_DELAY_SECONDS = 0.02


def _is_transient_lock(error: sqlite3.OperationalError) -> bool:
    """Windows reports WAL contention as "readonly" as well as "locked"/"busy".

    ``busy_timeout`` does not cover every case: opening the shared-memory file
    while another connection is recovering the WAL surfaces as
    "attempt to write a readonly database". Treating that as fatal made every
    concurrent writer fail on the first collision.
    """
    message = str(error).lower()
    return "locked" in message or "busy" in message or "readonly" in message


def _begin_immediate(connection: sqlite3.Connection) -> None:
    """Start a write transaction, retrying only when nothing has begun yet.

    A failed ``BEGIN`` leaves no transaction open, so retrying it cannot duplicate
    a statement. A failure inside the body is never retried here.
    """
    for attempt in range(_BEGIN_MAX_ATTEMPTS):
        try:
            connection.execute("BEGIN IMMEDIATE")
            return
        except sqlite3.OperationalError as error:
            if not _is_transient_lock(error) or attempt == _BEGIN_MAX_ATTEMPTS - 1:
                raise
            time.sleep(_BEGIN_RETRY_DELAY_SECONDS * (attempt + 1))


def _enable_wal(connection: sqlite3.Connection) -> None:
    """Switch the database to WAL once, without racing an active writer.

    Setting ``journal_mode`` needs a lock even when the mode is already WAL, so
    asking first avoids an unnecessary write on every connection.
    """
    for attempt in range(_WAL_SETUP_MAX_ATTEMPTS):
        try:
            current = connection.execute("PRAGMA journal_mode").fetchone()
            if current is not None and str(current[0]).lower() == "wal":
                return
            connection.execute("PRAGMA journal_mode = WAL")
            return
        except sqlite3.OperationalError as error:
            if not _is_transient_lock(error) or attempt == _WAL_SETUP_MAX_ATTEMPTS - 1:
                raise
            time.sleep(_WAL_SETUP_RETRY_DELAY_SECONDS)


class SQLiteDatabase:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA foreign_keys = ON")
            _enable_wal(connection)
        except Exception:
            connection.close()
            raise
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with write_lock_for(self.path):
            connection = self._begin()
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()
            finally:
                connection.close()

    def _begin(self) -> sqlite3.Connection:
        """Open a connection and start a write transaction, retrying from scratch.

        A connection that fails to attach to the WAL shared-memory file is marked
        read-only for its whole life, so retrying ``BEGIN`` on it can never
        succeed. Only a new connection can recover, and a failed ``BEGIN`` has
        written nothing, so replacing the connection is safe.
        """
        for attempt in range(_BEGIN_MAX_ATTEMPTS):
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                return connection
            except sqlite3.OperationalError as error:
                connection.close()
                if not _is_transient_lock(error) or attempt == _BEGIN_MAX_ATTEMPTS - 1:
                    raise
                time.sleep(_BEGIN_RETRY_DELAY_SECONDS * (attempt + 1))
        raise AssertionError("unreachable")
