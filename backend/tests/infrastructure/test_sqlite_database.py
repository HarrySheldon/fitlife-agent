import pytest

from backend.infrastructure.postgres.database import PostgresDatabase
from backend.infrastructure.postgres.errors import (
    DatabaseIntegrityError,
    DatabaseOperationalError,
)


def test_connection_targets_isolated_schema_and_pings(make_isolated_pg_db):
    database = make_isolated_pg_db(initialize=False)

    assert database.ping() is True
    with database.connection() as connection:
        row = connection.execute("SELECT current_schema() AS schema_name").fetchone()
        assert row["schema_name"] == database.target_schema
        assert row[0] == database.target_schema


def test_connection_rolls_back_uncommitted_writes_on_exit(make_isolated_pg_db):
    database = make_isolated_pg_db(initialize=False)
    with database.transaction() as connection:
        connection.execute("CREATE TABLE entries (value TEXT NOT NULL)")

    with database.connection() as connection:
        connection.execute("BEGIN")
        connection.execute("INSERT INTO entries (value) VALUES (?)", ("uncommitted",))

    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0


def test_transaction_commits_table_creation_and_inserted_value(make_isolated_pg_db):
    database = make_isolated_pg_db(initialize=False)

    with database.transaction() as connection:
        connection.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO entries (id, value) VALUES (?, ?)", (1, "committed"))

    with database.connection() as connection:
        row = connection.execute("SELECT id, value FROM entries").fetchone()
        assert tuple(row) == (1, "committed")
        assert dict(row) == {"id": 1, "value": "committed"}


def test_transaction_rolls_back_all_writes_when_a_statement_fails(make_isolated_pg_db):
    database = make_isolated_pg_db(initialize=False)
    with database.transaction() as connection:
        connection.execute("CREATE TABLE entries (value TEXT UNIQUE NOT NULL)")

    with pytest.raises(DatabaseIntegrityError):
        with database.transaction() as connection:
            connection.execute("INSERT INTO entries (value) VALUES (?)", ("duplicate",))
            connection.execute("INSERT INTO entries (value) VALUES (?)", ("duplicate",))

    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0


def test_savepoint_isolates_failed_statement_within_transaction(make_isolated_pg_db):
    database = make_isolated_pg_db(initialize=False)
    with database.transaction() as connection:
        connection.execute("CREATE TABLE entries (value TEXT UNIQUE NOT NULL)")

    with database.transaction() as connection:
        connection.execute("INSERT INTO entries (value) VALUES (?)", ("first",))
        with pytest.raises(DatabaseIntegrityError):
            with connection.savepoint():
                connection.execute("INSERT INTO entries (value) VALUES (?)", ("first",))
        connection.execute("INSERT INTO entries (value) VALUES (?)", ("second",))

    with database.connection() as connection:
        values = [row[0] for row in connection.execute("SELECT value FROM entries ORDER BY value").fetchall()]
        assert values == ["first", "second"]


def test_translate_sql_escapes_percent_without_positional_params(make_isolated_pg_db):
    database = make_isolated_pg_db(initialize=False)
    with database.connection() as connection:
        row = connection.execute("SELECT '100% pure' AS label").fetchone()
        assert row["label"] == "100% pure"


def test_invalid_sql_raises_database_operational_error(make_isolated_pg_db):
    database = make_isolated_pg_db(initialize=False)
    with pytest.raises(DatabaseOperationalError):
        with database.connection() as connection:
            connection.execute("SELECT * FROM missing_table_xyz")


def test_empty_dsn_is_rejected():
    with pytest.raises(ValueError, match="PostgreSQL DSN"):
        PostgresDatabase("")
