import json

import pytest

from backend.infrastructure.postgres.backup import (
    backup_postgres_database,
    verify_backup_file,
    verify_postgres_database,
)


def test_backup_uses_consistent_postgres_snapshot_and_reports_checksum(tmp_path, pg_db):
    with pg_db.transaction() as connection:
        connection.execute(
            "INSERT INTO users (user_id, email, display_name, password_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("user-backup", "backup@example.com", "Backup User", "hash", "2026-11-26T00:00:00Z"),
        )

    destination = tmp_path / "backups" / "release.json"
    result = backup_postgres_database(pg_db, destination, prefer_pg_dump=False)

    assert result.path == destination.resolve()
    assert result.path.exists()
    assert result.integrity_check == "ok"
    assert len(result.checksum or "") == 64
    assert result.user_count == 1
    assert result.backup_format == "logical_snapshot"

    verified = verify_backup_file(destination)
    assert verified.integrity_check == "ok"
    assert verified.checksum == result.checksum
    assert verified.user_count == 1
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["tables"]["users"][0]["user_id"] == "user-backup"


def test_verify_postgres_database_handles_uninitialized_schema(make_isolated_pg_db):
    empty_db = make_isolated_pg_db(initialize=False)

    verified = verify_postgres_database(empty_db)

    assert verified.integrity_check == "ok"
    assert verified.schema_version is None
    assert verified.user_count == 0
    assert verified.backup_format == "live_verify"


def test_verify_backup_file_rejects_corrupt_logical_payload(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text('{"unexpected": true}', encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid FitLife PostgreSQL logical backup payload"):
        verify_backup_file(broken)
