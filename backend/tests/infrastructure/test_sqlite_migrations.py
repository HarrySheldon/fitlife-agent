import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import (
    Migration,
    MigrationError,
    run_migrations,
)


def test_migrations_run_in_order_and_are_idempotent(tmp_path):
    database = SQLiteDatabase(tmp_path / "app.db")
    migrations = [
        Migration(
            version=2,
            name="add_notes",
            statements=("ALTER TABLE training_log ADD COLUMN notes TEXT",),
        ),
        Migration(
            version=1,
            name="create_training_log",
            statements=(
                "CREATE TABLE training_log (id INTEGER PRIMARY KEY)",
            ),
        ),
    ]

    run_migrations(database, migrations)
    run_migrations(database, migrations)

    with database.connection() as connection:
        applied = connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
        migration_columns = connection.execute(
            "PRAGMA table_info(schema_migrations)"
        ).fetchall()
        training_log_columns = connection.execute(
            "PRAGMA table_info(training_log)"
        ).fetchall()

    assert [(row["version"], row["name"]) for row in applied] == [
        (1, "create_training_log"),
        (2, "add_notes"),
    ]
    assert [row["name"] for row in migration_columns] == [
        "version",
        "name",
        "checksum",
        "applied_at",
    ]
    assert [row["name"] for row in training_log_columns] == ["id", "notes"]


def test_changing_an_applied_migration_raises_checksum_error(tmp_path):
    database = SQLiteDatabase(tmp_path / "app.db")
    original = Migration(
        version=1,
        name="create_entries",
        statements=("CREATE TABLE entries (id INTEGER PRIMARY KEY)",),
    )
    changed = Migration(
        version=1,
        name="create_entries",
        statements=(
            "CREATE TABLE entries (id INTEGER PRIMARY KEY, notes TEXT)",
        ),
    )
    run_migrations(database, [original])

    with pytest.raises(MigrationError, match="checksum"):
        run_migrations(database, [changed])


def test_applied_migration_missing_from_complete_set_is_rejected_unchanged(
    tmp_path,
):
    database = SQLiteDatabase(tmp_path / "app.db")
    migration = Migration(
        version=1,
        name="create_entries",
        statements=("CREATE TABLE entries (id INTEGER PRIMARY KEY)",),
    )
    run_migrations(database, [migration])

    with database.connection() as connection:
        before_history = connection.execute(
            "SELECT version, name, checksum, applied_at FROM schema_migrations"
        ).fetchall()
        before_schema = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()

    with pytest.raises(MigrationError, match="not supplied"):
        run_migrations(database, [])

    with database.connection() as connection:
        after_history = connection.execute(
            "SELECT version, name, checksum, applied_at FROM schema_migrations"
        ).fetchall()
        after_schema = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()

    assert [tuple(row) for row in after_history] == [
        tuple(row) for row in before_history
    ]
    assert [tuple(row) for row in after_schema] == [
        tuple(row) for row in before_schema
    ]


def test_preflight_drift_rejection_happens_before_pending_migration(tmp_path):
    database = SQLiteDatabase(tmp_path / "app.db")
    applied_v2 = Migration(
        version=2,
        name="create_version_two",
        statements=("CREATE TABLE version_two (id INTEGER PRIMARY KEY)",),
    )
    run_migrations(database, [applied_v2])
    pending_v1 = Migration(
        version=1,
        name="create_version_one",
        statements=("CREATE TABLE version_one (id INTEGER PRIMARY KEY)",),
    )
    changed_v2 = Migration(
        version=2,
        name="create_version_two",
        statements=(
            "CREATE TABLE version_two (id INTEGER PRIMARY KEY, notes TEXT)",
        ),
    )

    with pytest.raises(MigrationError, match="checksum"):
        run_migrations(database, [pending_v1, changed_v2])

    with database.connection() as connection:
        version_one = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'version_one'"
        ).fetchone()
        applied_versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()

    assert version_one is None
    assert [row["version"] for row in applied_versions] == [2]


def test_concurrent_runners_apply_new_migration_once(tmp_path):
    database = SQLiteDatabase(tmp_path / "app.db")
    migration = Migration(
        version=1,
        name="create_entries",
        statements=("CREATE TABLE entries (id INTEGER PRIMARY KEY)",),
    )
    barrier = Barrier(2)

    def migrate():
        barrier.wait(timeout=5)
        run_migrations(database, [migration])

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(migrate) for _ in range(2)]
        for future in futures:
            future.result(timeout=10)

    with database.connection() as connection:
        applied_count = connection.execute(
            "SELECT COUNT(*) AS count FROM schema_migrations"
        ).fetchone()["count"]
        entries = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'entries'"
        ).fetchone()

    assert applied_count == 1
    assert entries["name"] == "entries"


def test_failed_migration_rolls_back_schema_and_metadata(tmp_path):
    database = SQLiteDatabase(tmp_path / "app.db")
    broken = Migration(
        version=1,
        name="broken",
        statements=(
            "CREATE TABLE partial_table (id INTEGER PRIMARY KEY)",
            "INSERT INTO missing_table (id) VALUES (1)",
        ),
    )

    with pytest.raises(sqlite3.OperationalError):
        run_migrations(database, [broken])

    with database.connection() as connection:
        partial_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'partial_table'"
        ).fetchone()
        applied_count = connection.execute(
            "SELECT COUNT(*) AS count FROM schema_migrations"
        ).fetchone()["count"]

    assert partial_table is None
    assert applied_count == 0


@pytest.mark.parametrize(
    "migrations",
    [
        [Migration(version=0, name="invalid", statements=())],
        [
            Migration(version=1, name="first", statements=()),
            Migration(version=1, name="duplicate", statements=()),
        ],
    ],
)
def test_migration_versions_must_be_unique_positive_integers(
    tmp_path, migrations
):
    database = SQLiteDatabase(tmp_path / "app.db")

    with pytest.raises(MigrationError):
        run_migrations(database, migrations)
