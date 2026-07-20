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
