from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd
from pydantic import ValidationError

from backend.infrastructure.repositories.file_fitness_repository import (
    FileFitnessRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.schemas import MealRecord, UserProfile, WorkoutRecord
from backend.tools.data_access import MEAL_COLUMNS, WORKOUT_COLUMNS


_AMOUNT = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(.*?)\s*$")


class FitnessImportError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class FitnessImportResult:
    imported_count: int
    replayed: bool
    checksum: str


class SQLiteFitnessRepository:
    """Legacy FitnessRepository projection over authoritative record tables."""

    def __init__(
        self,
        database: SQLiteDatabase,
        *,
        profiles: FileFitnessRepository | None = None,
        data_dir: Path | None = None,
    ) -> None:
        self.database = database
        self.profiles = profiles or FileFitnessRepository()
        self.data_dir = Path(data_dir) if data_dir is not None else database.path.parent

    def read_profile(self, user_id: str | None = None) -> UserProfile:
        return self.profiles.read_profile(user_id)

    def write_profile(self, profile: UserProfile, user_id: str | None = None) -> None:
        self.profiles.write_profile(profile, user_id)

    def update_profile_atomically(
        self,
        update: Callable[[UserProfile], UserProfile],
        user_id: str | None = None,
    ) -> UserProfile:
        return self.profiles.update_profile_atomically(update, user_id)

    def read_meals(self, user_id: str | None = None) -> pd.DataFrame:
        if user_id is None:
            return pd.DataFrame(columns=MEAL_COLUMNS)
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT meals.log_date, meals.name, meal_items.*
                FROM meals JOIN meal_items ON meal_items.meal_id = meals.id
                WHERE meals.user_id = ?
                ORDER BY meals.log_date, meals.position, meal_items.created_at,
                         meal_items.id
                """,
                (user_id,),
            ).fetchall()
        records = []
        for row in rows:
            provenance = _object(row["provenance_json"])
            raw = provenance.get("raw")
            projection = provenance.get("legacy_projection")
            amount = (
                projection.get("amount")
                if isinstance(projection, dict)
                else raw.get("amount") if isinstance(raw, dict) else None
            )
            records.append(
                {
                    "date": row["log_date"],
                    "meal": row["name"],
                    "food": row["food_name"],
                    "amount": amount or _format_amount(row["amount"], row["unit"]),
                    "calories": row["calories"],
                    "protein": row["protein"],
                    "carbs": row["carbs"],
                    "fat": row["fat"],
                }
            )
        return pd.DataFrame(records, columns=MEAL_COLUMNS)

    def read_workouts(self, user_id: str | None = None) -> pd.DataFrame:
        if user_id is None:
            return pd.DataFrame(columns=WORKOUT_COLUMNS)
        with self.database.connection() as connection:
            sessions = connection.execute(
                """
                SELECT * FROM training_sessions WHERE user_id = ?
                ORDER BY log_date, created_at, id
                """,
                (user_id,),
            ).fetchall()
            records = [_workout_projection(connection, row) for row in sessions]
        return pd.DataFrame(records, columns=WORKOUT_COLUMNS)

    def append_meal(self, record: MealRecord, user_id: str | None = None) -> None:
        user = _required_user(user_id)
        with self.database.transaction() as connection:
            _append_meal(connection, user, record, entry_method="form")

    def append_workout(
        self, record: WorkoutRecord, user_id: str | None = None
    ) -> None:
        user = _required_user(user_id)
        with self.database.transaction() as connection:
            _append_workout(connection, user, record, entry_method="form")

    def import_meals_csv(
        self, user_id: str, content: bytes
    ) -> FitnessImportResult:
        records = _parse_csv(content, MEAL_COLUMNS, MealRecord)
        return self._import(user_id, "meals", content, records, _append_meal)

    def import_workouts_csv(
        self, user_id: str, content: bytes
    ) -> FitnessImportResult:
        records = _parse_csv(content, WORKOUT_COLUMNS, WorkoutRecord)
        return self._import(user_id, "workouts", content, records, _append_workout)

    def _import(self, user_id, kind, content, records, writer) -> FitnessImportResult:
        user = _required_user(user_id)
        checksum = hashlib.sha256(content).hexdigest()
        operation = f"csv_upload:{kind}:{user}:{checksum}"
        with self.database.connection() as connection:
            existing = connection.execute(
                "SELECT status FROM data_migrations WHERE migration_key = ?",
                (operation,),
            ).fetchone()
        if existing is not None and existing["status"] == "completed":
            return FitnessImportResult(0, True, checksum)

        archive = _archive_upload(self.data_dir, user, kind, checksum, content)
        with self.database.transaction() as connection:
            for record in records:
                writer(connection, user, record, entry_method="csv")
            connection.execute(
                """
                INSERT INTO data_migrations (
                    migration_key, user_id, checksum, status,
                    source_backup_path, details_json, completed_at
                ) VALUES (?, ?, ?, 'completed', ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(migration_key) DO UPDATE SET
                    status = 'completed', source_backup_path = excluded.source_backup_path,
                    details_json = excluded.details_json,
                    completed_at = CURRENT_TIMESTAMP
                """,
                (
                    operation, user, checksum, str(archive),
                    json.dumps({"imported_count": len(records)}, separators=(",", ":")),
                ),
            )
        return FitnessImportResult(len(records), False, checksum)


def _append_meal(connection, user_id: str, record: MealRecord, *, entry_method: str) -> None:
    row = connection.execute(
        """
        SELECT id FROM meals
        WHERE user_id = ? AND log_date = ? AND name = ?
        ORDER BY position LIMIT 1
        """,
        (user_id, record.date, record.meal),
    ).fetchone()
    if row is None:
        position = connection.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM meals WHERE user_id = ? AND log_date = ?",
            (user_id, record.date),
        ).fetchone()[0]
        meal_id = uuid4().hex
        connection.execute(
            """
            INSERT INTO meals (
                id, user_id, log_date, name, meal_type, position, entry_method
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (meal_id, user_id, record.date, record.meal, record.meal, position, entry_method),
        )
    else:
        meal_id = row["id"]
    amount, unit = _parse_amount(record.amount)
    connection.execute(
        """
        INSERT INTO meal_items (
            id, meal_id, food_name, amount, unit, basis_type,
            calories, carbs, protein, fat, source, provenance_json
        ) VALUES (?, ?, ?, ?, ?, 'per_serving', ?, ?, ?, ?, 'user_custom', ?)
        """,
        (
            uuid4().hex, meal_id, record.food, amount, unit, record.calories,
            record.carbs, record.protein, record.fat,
            json.dumps(
                {"entry_method": entry_method, "legacy_projection": record.model_dump()},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ),
        ),
    )


def _append_workout(
    connection, user_id: str, record: WorkoutRecord, *, entry_method: str
) -> None:
    session_id = uuid4().hex
    duration = record.duration_min if record.duration_min > 0 else None
    projection = json.dumps(
        {"legacy_projection": record.model_dump()},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    connection.execute(
        """
        INSERT INTO training_sessions (
            id, user_id, log_date, title, duration_min, entry_method, estimate_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (session_id, user_id, record.date, record.exercise, duration, entry_method, projection),
    )
    kind = record.type.strip().casefold()
    if kind == "strength" and record.exercise:
        strength_id = uuid4().hex
        connection.execute(
            """
            INSERT INTO strength_exercises (
                id, session_id, exercise_name, primary_muscle,
                provenance_json, position
            ) VALUES (?, ?, ?, ?, ?, 1)
            """,
            (
                strength_id, session_id, record.exercise,
                record.muscle_group or "unspecified", projection,
            ),
        )
        sets = int(record.sets or 0)
        reps = int(record.reps or 0)
        if sets > 0 and reps > 0:
            for number in range(1, min(sets, 100) + 1):
                connection.execute(
                    """
                    INSERT INTO strength_sets (
                        id, strength_exercise_id, set_number, reps, load_kg
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (uuid4().hex, strength_id, number, reps, record.weight or None),
                )
    elif kind == "cardio" and record.exercise and duration is not None:
        connection.execute(
            """
            INSERT INTO cardio_items (
                id, session_id, activity_name, duration_min,
                estimate_json, provenance_json, position
            ) VALUES (?, ?, ?, ?, '{}', ?, 1)
            """,
            (uuid4().hex, session_id, record.exercise, duration, projection),
        )


def _workout_projection(connection, session) -> dict[str, object]:
    estimate = _object(session["estimate_json"])
    saved = estimate.get("legacy_projection")
    if isinstance(saved, dict):
        return {column: saved.get(column, 0) for column in WORKOUT_COLUMNS}
    strength = connection.execute(
        "SELECT * FROM strength_exercises WHERE session_id = ? ORDER BY position LIMIT 1",
        (session["id"],),
    ).fetchone()
    if strength is not None:
        sets = connection.execute(
            "SELECT COUNT(*) AS sets, COALESCE(AVG(reps), 0) AS reps, COALESCE(AVG(load_kg), 0) AS weight FROM strength_sets WHERE strength_exercise_id = ?",
            (strength["id"],),
        ).fetchone()
        return _workout_row(
            session, "strength", strength["exercise_name"],
            strength["primary_muscle"], sets["sets"], sets["reps"], sets["weight"],
        )
    cardio = connection.execute(
        "SELECT * FROM cardio_items WHERE session_id = ? ORDER BY position LIMIT 1",
        (session["id"],),
    ).fetchone()
    if cardio is not None:
        return _workout_row(
            session, "cardio", cardio["activity_name"], "cardiovascular", 0, 0, 0,
        )
    provenance = estimate.get("legacy_provenance")
    raw = provenance.get("raw") if isinstance(provenance, dict) else None
    if isinstance(raw, dict):
        return {column: raw.get(column, 0) for column in WORKOUT_COLUMNS}
    return _workout_row(session, "unknown", session["title"], "", 0, 0, 0)


def _workout_row(session, kind, exercise, muscle, sets, reps, weight):
    return {
        "date": session["log_date"], "type": kind, "exercise": exercise,
        "muscle_group": muscle, "sets": sets, "reps": reps, "weight": weight,
        "duration_min": session["duration_min"] or 0,
    }


def _parse_csv(content: bytes, columns: list[str], model):
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise FitnessImportError("CSV_ENCODING_INVALID") from None
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not set(columns).issubset(reader.fieldnames or ()):
        raise FitnessImportError("CSV_HEADERS_INVALID")
    records = []
    try:
        for raw in reader:
            if None in raw:
                raise FitnessImportError("CSV_ROW_INVALID")
            records.append(model.model_validate({key: raw[key] for key in columns}))
    except (ValidationError, ValueError):
        raise FitnessImportError("CSV_ROW_INVALID") from None
    return tuple(records)


def _archive_upload(data_dir: Path, user_id: str, kind: str, checksum: str, content: bytes) -> Path:
    root = data_dir / "users" / user_id / "imports"
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = root / f"{kind}-{timestamp}-{checksum[:12]}.csv"
    path.write_bytes(content)
    os.chmod(path, stat.S_IREAD)
    return path


def _parse_amount(value: str) -> tuple[float, str]:
    match = _AMOUNT.fullmatch(value)
    if match is None or float(match.group(1)) <= 0:
        return 1.0, "serving"
    return float(match.group(1)), match.group(2) or "serving"


def _format_amount(amount: float, unit: str) -> str:
    value = int(amount) if float(amount).is_integer() else amount
    return f"{value} {unit}".strip()


def _object(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _required_user(user_id: str | None) -> str:
    if not user_id:
        raise ValueError("SQLite fitness records require a user")
    return user_id
