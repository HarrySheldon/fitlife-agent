from backend.config import get_settings
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


def get_database() -> SQLiteDatabase:
    return SQLiteDatabase(get_settings().database_path)


def initialize_database() -> None:
    run_migrations(get_database(), RECORDS_MIGRATIONS)


def ensure_database_ready(database: SQLiteDatabase | None = None) -> SQLiteDatabase:
    """Ensure SQLite schema migrations up through v15 are applied before repository I/O."""
    db = database or get_database()
    with db.connection() as connection:
        has_users = (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users'"
            ).fetchone()
            is not None
        )
        goal_cols = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(overall_goal_versions)").fetchall()
        }
    if not has_users or "target_weight_kg" not in goal_cols:
        run_migrations(db, RECORDS_MIGRATIONS)
    return db
