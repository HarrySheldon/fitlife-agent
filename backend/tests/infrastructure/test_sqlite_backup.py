import sqlite3

import pytest

from backend.infrastructure.sqlite.backup import backup_database
from backend.infrastructure.sqlite.database import SQLiteDatabase


def test_backup_uses_consistent_sqlite_image_and_reports_checksum(tmp_path):
    database = SQLiteDatabase(tmp_path / "live.sqlite3")
    with database.transaction() as connection:
        connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO records (value) VALUES ('preserved')")

    result = backup_database(database, tmp_path / "backups" / "release.sqlite3")

    assert result.path.exists()
    assert result.bytes == result.path.stat().st_size
    assert len(result.checksum) == 64
    with sqlite3.connect(result.path) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT value FROM records").fetchone()[0] == "preserved"


def test_backup_rejects_live_database_as_destination(tmp_path):
    database = SQLiteDatabase(tmp_path / "live.sqlite3")

    with pytest.raises(ValueError):
        backup_database(database, database.path)
