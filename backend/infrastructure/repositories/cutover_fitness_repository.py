from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pandas as pd

from backend.config import get_settings
from backend.infrastructure.migration.legacy_csv import MIGRATION_VERSION
from backend.infrastructure.repositories.file_fitness_repository import FileFitnessRepository
from backend.infrastructure.repositories.sqlite_fitness_repository import SQLiteFitnessRepository
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.runtime import get_database
from backend.schemas import MealRecord, UserProfile, WorkoutRecord


class CutoverFitnessRepository:
    def __init__(
        self,
        database: SQLiteDatabase,
        *,
        file_repository: FileFitnessRepository | None = None,
        sqlite_repository: SQLiteFitnessRepository | None = None,
    ) -> None:
        self.database = database
        self.file = file_repository or FileFitnessRepository()
        self.sqlite = sqlite_repository or SQLiteFitnessRepository(database)

    def is_cutover(self, user_id: str | None) -> bool:
        if user_id is None:
            return False
        try:
            with self.database.connection() as connection:
                row = connection.execute(
                    """
                    SELECT status FROM data_migrations
                    WHERE migration_key = ? AND user_id = ?
                    """,
                    (f"{MIGRATION_VERSION}:{user_id}", user_id),
                ).fetchone()
        except sqlite3.OperationalError as error:
            if "no such table" not in str(error).casefold():
                raise
            return False
        return row is not None and row["status"] == "completed"

    def _records(self, user_id: str | None):
        return self.sqlite if self.is_cutover(user_id) else self.file

    def read_profile(self, user_id: str | None = None) -> UserProfile:
        return self.file.read_profile(user_id)

    def write_profile(self, profile: UserProfile, user_id: str | None = None) -> None:
        self.file.write_profile(profile, user_id)

    def update_profile_atomically(
        self, update: Callable[[UserProfile], UserProfile], user_id: str | None = None
    ) -> UserProfile:
        return self.file.update_profile_atomically(update, user_id)

    def read_meals(self, user_id: str | None = None) -> pd.DataFrame:
        return self._records(user_id).read_meals(user_id)

    def read_workouts(self, user_id: str | None = None) -> pd.DataFrame:
        return self._records(user_id).read_workouts(user_id)

    def append_meal(self, record: MealRecord, user_id: str | None = None) -> None:
        self._records(user_id).append_meal(record, user_id)

    def append_workout(self, record: WorkoutRecord, user_id: str | None = None) -> None:
        self._records(user_id).append_workout(record, user_id)


def get_fitness_repository() -> CutoverFitnessRepository:
    database = get_database()
    return CutoverFitnessRepository(
        database,
        sqlite_repository=SQLiteFitnessRepository(
            database,
            data_dir=get_settings().data_dir,
        ),
    )
