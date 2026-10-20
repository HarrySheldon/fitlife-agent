import sqlite3
from pathlib import Path

import pytest

from backend.infrastructure.sqlite import SQLiteDatabase


def test_file_connection_enables_sqlite_safety_pragmas(tmp_path):
    database = SQLiteDatabase(tmp_path / "nested" / "app.db")

    with database.connection() as connection:
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]

    assert foreign_keys == 1
    assert journal_mode == "wal"
    assert busy_timeout == 5000


def test_connection_closes_after_context_exit(tmp_path):
    database = SQLiteDatabase(tmp_path / "app.db")

    with database.connection() as connection:
        connection.execute("SELECT 1")

    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")


def test_connection_closes_when_pragma_setup_fails(tmp_path, monkeypatch):
    setup_error = RuntimeError("pragma setup failed")

    class TrackingConnection:
        def __init__(self):
            self.closed = False
            self.row_factory = None

        def execute(self, statement):
            raise setup_error

        def close(self):
            self.closed = True

    tracking_connection = TrackingConnection()
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: tracking_connection)
    database = SQLiteDatabase(tmp_path / "app.db")

    with pytest.raises(RuntimeError) as raised:
        with database.connection():
            pass

    assert raised.value is setup_error
    assert tracking_connection.closed is True


class _Probe:
    """What ``PRAGMA journal_mode`` returns before the mode is switched."""

    def __init__(self, mode: str) -> None:
        self._mode = mode

    def fetchone(self):
        return (self._mode,)


def test_locked_wal_setup_retries_after_setting_busy_timeout(monkeypatch):
    class TrackingConnection:
        def __init__(self):
            self.calls = []
            self.closed = False
            self.row_factory = None
            self.wal_attempts = 0

        def execute(self, statement):
            self.calls.append(statement)
            if statement == "PRAGMA journal_mode":
                return _Probe("delete")
            if statement == "PRAGMA journal_mode = WAL":
                self.wal_attempts += 1
                if self.wal_attempts == 1:
                    raise sqlite3.OperationalError("database is locked")
            return None

        def close(self):
            self.closed = True

    tracking_connection = TrackingConnection()
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: tracking_connection)
    database = SQLiteDatabase(Path("unused.db"))

    with database.connection():
        pass

    assert tracking_connection.calls == [
        "PRAGMA busy_timeout = 5000",
        "PRAGMA foreign_keys = ON",
        "PRAGMA journal_mode",
        "PRAGMA journal_mode = WAL",
        # The retry re-reads the mode first: another process may have switched it
        # while this one was waiting for the lock.
        "PRAGMA journal_mode",
        "PRAGMA journal_mode = WAL",
    ]
    assert tracking_connection.closed is True


def test_a_database_already_in_wal_is_never_written_to_on_connect(monkeypatch):
    """Asking first is what removed the concurrent-writer failure.

    ``PRAGMA journal_mode = WAL`` needs a lock even when the mode is already WAL,
    and SQLite reports that contention as "attempt to write a readonly database".
    """

    class TrackingConnection:
        def __init__(self):
            self.calls = []
            self.closed = False
            self.row_factory = None

        def execute(self, statement):
            self.calls.append(statement)
            if statement == "PRAGMA journal_mode":
                return _Probe("wal")
            return None

        def close(self):
            self.closed = True

    tracking_connection = TrackingConnection()
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: tracking_connection)
    database = SQLiteDatabase(Path("unused.db"))

    with database.connection():
        pass

    assert "PRAGMA journal_mode = WAL" not in tracking_connection.calls
    assert tracking_connection.calls == [
        "PRAGMA busy_timeout = 5000",
        "PRAGMA foreign_keys = ON",
        "PRAGMA journal_mode",
    ]


def test_non_lock_wal_setup_error_does_not_retry_and_closes(monkeypatch):
    setup_error = sqlite3.OperationalError("disk I/O error")

    class TrackingConnection:
        def __init__(self):
            self.closed = False
            self.row_factory = None
            self.wal_attempts = 0

        def execute(self, statement):
            if statement == "PRAGMA journal_mode":
                return _Probe("delete")
            if statement == "PRAGMA journal_mode = WAL":
                self.wal_attempts += 1
                raise setup_error
            return None

        def close(self):
            self.closed = True

    tracking_connection = TrackingConnection()
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: tracking_connection)
    database = SQLiteDatabase(Path("unused.db"))

    with pytest.raises(sqlite3.OperationalError) as raised:
        with database.connection():
            pass

    assert raised.value is setup_error
    assert tracking_connection.wal_attempts == 1
    assert tracking_connection.closed is True


def test_transaction_commits_table_creation_and_inserted_value(tmp_path):
    database = SQLiteDatabase(tmp_path / "app.db")

    with database.transaction() as connection:
        connection.execute("CREATE TABLE entries (value TEXT NOT NULL)")
        connection.execute("INSERT INTO entries (value) VALUES (?)", ("saved",))

    with database.connection() as connection:
        row = connection.execute("SELECT value FROM entries").fetchone()

    assert row["value"] == "saved"


def test_transaction_rolls_back_all_writes_when_a_statement_fails(tmp_path):
    database = SQLiteDatabase(tmp_path / "app.db")
    with database.connection() as connection:
        connection.execute("CREATE TABLE entries (value TEXT UNIQUE NOT NULL)")

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute("INSERT INTO entries (value) VALUES (?)", ("duplicate",))
            connection.execute("INSERT INTO entries (value) VALUES (?)", ("duplicate",))

    with database.connection() as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM entries").fetchone()

    assert row["count"] == 0
