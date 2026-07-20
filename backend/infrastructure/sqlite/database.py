from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


_WAL_SETUP_MAX_ATTEMPTS = 3
_WAL_SETUP_RETRY_DELAY_SECONDS = 0.01


def _enable_wal(connection: sqlite3.Connection) -> None:
    for attempt in range(_WAL_SETUP_MAX_ATTEMPTS):
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            return
        except sqlite3.OperationalError as error:
            message = str(error).lower()
            is_lock_error = "locked" in message or "busy" in message
            if not is_lock_error or attempt == _WAL_SETUP_MAX_ATTEMPTS - 1:
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
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()
