from backend.config import get_settings
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


def get_database() -> SQLiteDatabase:
    return SQLiteDatabase(get_settings().database_path)


def initialize_database() -> None:
    run_migrations(get_database(), RECORDS_MIGRATIONS)
