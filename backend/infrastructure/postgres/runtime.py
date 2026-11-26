from __future__ import annotations

from backend import config as _config
from backend.infrastructure.postgres.database import PostgresDatabase, reset_database_pools
from backend.infrastructure.postgres.migrations import run_migrations
from backend.infrastructure.postgres.schema import RECORDS_MIGRATIONS


def get_database() -> PostgresDatabase:
    settings = _config.get_settings()
    return PostgresDatabase(
        settings.database_url,
        schema=settings.database_schema,
    )


def initialize_database() -> None:
    run_migrations(get_database(), RECORDS_MIGRATIONS)


def ensure_database_ready(database: PostgresDatabase | None = None) -> PostgresDatabase:
    """Ensure PostgreSQL schema migrations up through v16 are applied before repository I/O."""
    db = database or get_database()
    with db.connection() as connection:
        exists_row = connection.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = current_schema() AND table_name = 'schema_migrations'
            """
        ).fetchone()
        if exists_row is None:
            latest_version = 0
        else:
            version_row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()
            latest_version = int(version_row["version"]) if version_row is not None else 0
    expected_version = RECORDS_MIGRATIONS[-1].version
    if latest_version < expected_version:
        run_migrations(db, RECORDS_MIGRATIONS)
    return db


__all__ = [
    "ensure_database_ready",
    "get_database",
    "initialize_database",
    "reset_database_pools",
]
