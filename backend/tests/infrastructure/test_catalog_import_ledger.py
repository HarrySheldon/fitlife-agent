from __future__ import annotations

from pathlib import Path

import pytest

from backend.infrastructure.catalog.import_ledger import (
    CatalogImportError,
    CatalogImportLedger,
    CatalogMutationResult,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


CHECKSUM_A = "a" * 64
CHECKSUM_B = "b" * 64


def _database(tmp_path: Path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "catalog-ledger.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    with database.transaction() as connection:
        connection.execute(
            "CREATE TABLE import_probe (id TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
    return database


def test_catalog_import_completes_once_and_skips_the_same_checksum(tmp_path):
    database = _database(tmp_path)
    calls = 0

    def import_rows(connection):
        nonlocal calls
        calls += 1
        connection.execute(
            "INSERT INTO import_probe (id, value) VALUES ('row-1', 'first')"
        )
        return CatalogMutationResult(inserted_count=1)

    ledger = CatalogImportLedger(database)
    first = ledger.run("source-a", "v1", CHECKSUM_A, import_rows)
    second = ledger.run("source-a", "v1", CHECKSUM_A, import_rows)

    assert first.status == "completed"
    assert first.mutation.inserted_count == 1
    assert second.status == "skipped"
    assert calls == 1
    with database.connection() as connection:
        row = connection.execute(
            "SELECT * FROM catalog_imports WHERE source_name = 'source-a'"
        ).fetchone()
    assert row["checksum"] == CHECKSUM_A
    assert row["status"] == "completed"
    assert row["imported_count"] == 1


def test_catalog_import_rejects_checksum_drift_for_completed_version(tmp_path):
    database = _database(tmp_path)
    ledger = CatalogImportLedger(database)
    ledger.run(
        "source-a",
        "v1",
        CHECKSUM_A,
        lambda connection: CatalogMutationResult(),
    )

    with pytest.raises(CatalogImportError) as raised:
        ledger.run(
            "source-a",
            "v1",
            CHECKSUM_B,
            lambda connection: CatalogMutationResult(),
        )

    assert raised.value.code == "CATALOG_IMPORT_CHECKSUM_MISMATCH"
    with database.connection() as connection:
        row = connection.execute(
            "SELECT checksum, status FROM catalog_imports"
        ).fetchone()
    assert dict(row) == {"checksum": CHECKSUM_A, "status": "completed"}


def test_failed_catalog_import_rolls_back_rows_and_records_safe_failure(tmp_path):
    database = _database(tmp_path)

    def fail_after_write(connection):
        connection.execute(
            "INSERT INTO import_probe (id, value) VALUES ('row-1', 'partial')"
        )
        raise RuntimeError("raw source value must not enter the ledger")

    with pytest.raises(CatalogImportError) as raised:
        CatalogImportLedger(database).run(
            "source-a",
            "v2",
            CHECKSUM_A,
            fail_after_write,
        )

    assert raised.value.code == "CATALOG_IMPORT_FAILED"
    with database.connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) AS count FROM import_probe"
        ).fetchone()["count"] == 0
        row = connection.execute(
            "SELECT status, details_json FROM catalog_imports"
        ).fetchone()
    assert row["status"] == "failed"
    assert "raw source value" not in row["details_json"]
    assert "CATALOG_IMPORT_FAILED" in row["details_json"]


def test_failed_version_can_retry_with_the_same_checksum(tmp_path):
    database = _database(tmp_path)
    ledger = CatalogImportLedger(database)

    with pytest.raises(CatalogImportError):
        ledger.run(
            "source-a",
            "v2",
            CHECKSUM_A,
            lambda connection: (_ for _ in ()).throw(RuntimeError("failed")),
        )

    result = ledger.run(
        "source-a",
        "v2",
        CHECKSUM_A,
        lambda connection: CatalogMutationResult(unchanged_count=2),
    )

    assert result.status == "completed"
    assert result.mutation.unchanged_count == 2
    with database.connection() as connection:
        row = connection.execute(
            "SELECT status, imported_count, rejected_count FROM catalog_imports"
        ).fetchone()
    assert dict(row) == {
        "status": "completed",
        "imported_count": 2,
        "rejected_count": 0,
    }
