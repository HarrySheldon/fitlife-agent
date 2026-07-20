import sqlite3

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
