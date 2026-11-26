from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from backend.infrastructure.postgres.errors import DatabaseOperationalError
from backend.infrastructure.postgres.migrations import (
    Migration,
    MigrationError,
    run_migrations,
)


def test_migrations_run_in_order_and_are_idempotent(make_isolated_pg_db):
    database = make_isolated_pg_db(initialize=False)
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
            "SELECT column_name AS name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'schema_migrations' "
            "ORDER BY ordinal_position"
        ).fetchall()
        training_log_columns = connection.execute(
            "SELECT column_name AS name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'training_log' "
            "ORDER BY ordinal_position"
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


def test_changing_an_applied_migration_raises_checksum_error(make_isolated_pg_db):
    database = make_isolated_pg_db(initialize=False)
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
    make_isolated_pg_db,
):
    database = make_isolated_pg_db(initialize=False)
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
            "SELECT table_name AS name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        ).fetchall()

    with pytest.raises(MigrationError, match="not supplied"):
        run_migrations(database, [])

    with database.connection() as connection:
        after_history = connection.execute(
            "SELECT version, name, checksum, applied_at FROM schema_migrations"
        ).fetchall()
        after_schema = connection.execute(
            "SELECT table_name AS name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        ).fetchall()

    assert [tuple(row) for row in after_history] == [
        tuple(row) for row in before_history
    ]
    assert [tuple(row) for row in after_schema] == [
        tuple(row) for row in before_schema
    ]


def test_preflight_drift_rejection_happens_before_pending_migration(make_isolated_pg_db):
    database = make_isolated_pg_db(initialize=False)
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
            "SELECT table_name AS name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = 'version_one'"
        ).fetchone()
        applied_versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()

    assert version_one is None
    assert [row["version"] for row in applied_versions] == [2]


def test_concurrent_runners_apply_new_migration_once(make_isolated_pg_db):
    database = make_isolated_pg_db(initialize=False)
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
            "SELECT table_name AS name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = 'entries'"
        ).fetchone()

    assert applied_count == 1
    assert entries["name"] == "entries"


def test_failed_migration_rolls_back_schema_and_metadata(make_isolated_pg_db):
    database = make_isolated_pg_db(initialize=False)
    broken = Migration(
        version=1,
        name="broken",
        statements=(
            "CREATE TABLE partial_table (id INTEGER PRIMARY KEY)",
            "INSERT INTO missing_table (id) VALUES (1)",
        ),
    )

    with pytest.raises(DatabaseOperationalError):
        run_migrations(database, [broken])

    with database.connection() as connection:
        partial_table = connection.execute(
            "SELECT table_name AS name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = 'partial_table'"
        ).fetchone()
        migrations_table = connection.execute(
            "SELECT table_name AS name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = 'schema_migrations'"
        ).fetchone()

    assert partial_table is None
    assert migrations_table is None


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
    make_isolated_pg_db, migrations
):
    database = make_isolated_pg_db(initialize=False)

    with pytest.raises(MigrationError):
        run_migrations(database, migrations)
