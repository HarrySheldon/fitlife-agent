import sqlite3

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
