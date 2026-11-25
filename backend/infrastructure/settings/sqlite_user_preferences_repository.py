from __future__ import annotations

import re
from contextlib import nullcontext
from pathlib import Path

from backend.domain.model_connection import utc_now_iso
from backend.domain.user_preferences import UserPreferences
from backend.infrastructure.settings.file_user_preferences_repository import FileUserPreferencesRepository
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.runtime import ensure_database_ready
from backend.infrastructure.user_lifecycle import user_lifecycle_guard


_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class SQLiteUserPreferencesRepository:
    def __init__(self, database: SQLiteDatabase, data_dir: Path | None = None) -> None:
        self.database = database
        self.data_dir = Path(data_dir) if data_dir is not None else None

    def get(self, user_id: str) -> UserPreferences | None:
        if not _USER_ID_PATTERN.fullmatch(user_id):
            raise ValueError("Invalid user id")
        ensure_database_ready(self.database)
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT language, unit_system, timezone
                FROM user_preferences
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        if row is not None:
            return UserPreferences(
                language=row["language"],
                unit_system=row["unit_system"],
                timezone=row["timezone"],
            )
        if self.data_dir is not None:
            legacy_path = self.data_dir / "users" / user_id / "preferences.json"
            if legacy_path.is_file():
                return FileUserPreferencesRepository(self.data_dir).get(user_id)
        return None

    def save(self, user_id: str, preferences: UserPreferences) -> None:
        if not _USER_ID_PATTERN.fullmatch(user_id):
            raise ValueError("Invalid user id")
        ensure_database_ready(self.database)
        validated = UserPreferences.model_validate(preferences.model_dump())
        guard = (
            user_lifecycle_guard(self.data_dir, user_id)
            if self.data_dir is not None
            else nullcontext()
        )
        with guard, self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO user_preferences (
                    user_id, language, unit_system, timezone, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    language = excluded.language,
                    unit_system = excluded.unit_system,
                    timezone = excluded.timezone,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    validated.language,
                    validated.unit_system,
                    validated.timezone,
                    utc_now_iso(),
                ),
            )

    def delete_user_data(self, user_id: str) -> None:
        ensure_database_ready(self.database)
        with self.database.transaction() as connection:
            connection.execute(
                "DELETE FROM user_preferences WHERE user_id = ?",
                (user_id,),
            )
