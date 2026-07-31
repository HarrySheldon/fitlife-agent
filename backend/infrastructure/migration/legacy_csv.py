from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import stat
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from backend.infrastructure.sqlite.database import SQLiteDatabase


MIGRATION_VERSION = "legacy_csv_v1"
MEAL_HEADERS = (
    "date", "meal", "food", "amount", "calories", "protein", "carbs", "fat"
)
WORKOUT_HEADERS = (
    "date", "type", "exercise", "muscle_group", "sets", "reps", "weight",
    "duration_min",
)
_SAFE_USER_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_AMOUNT = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([^\d\s]+)?\s*$")


class LegacyMigrationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class LegacyMigrationResult:
    status: Literal["completed", "skipped", "failed"]
    meal_rows: int = 0
    meal_groups: int = 0
    workout_rows: int = 0
    backup_path: str | None = None
    backup_checksum: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class _MealRow:
    source_id: str
    log_date: str
    meal_label: str
    food: str
    amount: float
    unit: str
    calories: float
    protein: float
    carbs: float
    fat: float
    raw: dict[str, str]


@dataclass(frozen=True)
class _WorkoutRow:
    source_id: str
    log_date: str
    workout_type: str
    exercise: str
    muscle_group: str | None
    sets: int | None
    reps: int | None
    weight: float | None
    duration_min: float | None
    raw: dict[str, str]


class LegacyCsvMigrator:
    def __init__(self, database: SQLiteDatabase, data_dir: Path) -> None:
        self.database = database
        self.data_dir = Path(data_dir)

    def migrate_user(self, user_id: str) -> LegacyMigrationResult:
        user_root = self._user_root(user_id)
        migration_key = f"{MIGRATION_VERSION}:{user_id}"
        existing = self._ledger(migration_key)
        if existing is not None and existing["status"] == "completed":
            details = _json_object(existing["details_json"])
            return LegacyMigrationResult(
                status="skipped",
                meal_rows=int(details.get("meal_rows", 0)),
                meal_groups=int(details.get("meal_groups", 0)),
                workout_rows=int(details.get("workout_rows", 0)),
                backup_path=existing["source_backup_path"],
                backup_checksum=details.get("backup_checksum"),
            )

        meal_path = user_root / "meals.csv"
        workout_path = user_root / "workouts.csv"
        try:
            sources = {
                "meals.csv": _read_source(meal_path, MEAL_HEADERS),
                "workouts.csv": _read_source(workout_path, WORKOUT_HEADERS),
            }
            source_checksum = _source_checksum(sources)
            meals = _parse_meals(sources["meals.csv"])
            workouts = _parse_workouts(sources["workouts.csv"])
            backup_path, backup_checksum = _create_backup(
                user_root,
                user_id=user_id,
                migration_key=migration_key,
                sources=sources,
                source_checksum=source_checksum,
            )
            result = self._commit(
                user_id,
                migration_key=migration_key,
                source_checksum=source_checksum,
                meals=meals,
                workouts=workouts,
                backup_path=backup_path,
                backup_checksum=backup_checksum,
            )
            return result
        except Exception as error:
            code = (
                error.code
                if isinstance(error, LegacyMigrationError)
                else "LEGACY_MIGRATION_FAILED"
            )
            backup = locals().get("backup_path")
            backup_digest = locals().get("backup_checksum")
            self._record_failure(
                user_id,
                migration_key,
                locals().get("source_checksum", "0" * 64),
                str(backup) if backup else None,
                backup_digest,
                code,
            )
            return LegacyMigrationResult(
                status="failed",
                backup_path=str(backup) if backup else None,
                backup_checksum=backup_digest,
                error_code=code,
            )

    def _commit(
        self,
        user_id: str,
        *,
        migration_key: str,
        source_checksum: str,
        meals: tuple[_MealRow, ...],
        workouts: tuple[_WorkoutRow, ...],
        backup_path: Path,
        backup_checksum: str,
    ) -> LegacyMigrationResult:
        groups = _group_meals(meals)
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO data_migrations (
                    migration_key, user_id, checksum, status,
                    source_backup_path, details_json, started_at, completed_at
                ) VALUES (?, ?, ?, 'running', ?, '{}', CURRENT_TIMESTAMP, NULL)
                ON CONFLICT(migration_key) DO UPDATE SET
                    user_id = excluded.user_id,
                    checksum = excluded.checksum,
                    status = 'running',
                    source_backup_path = excluded.source_backup_path,
                    details_json = '{}',
                    started_at = CURRENT_TIMESTAMP,
                    completed_at = NULL
                """,
                (migration_key, user_id, source_checksum, str(backup_path)),
            )
            _insert_meals(connection, user_id, groups)
            _insert_workouts(connection, user_id, workouts)
            _reconcile(connection, user_id, meals, groups, workouts)
            details = {
                "meal_rows": len(meals),
                "meal_groups": len(groups),
                "workout_rows": len(workouts),
                "backup_checksum": backup_checksum,
            }
            connection.execute(
                """
                UPDATE data_migrations
                SET status = 'completed', details_json = ?,
                    completed_at = CURRENT_TIMESTAMP
                WHERE migration_key = ?
                """,
                (_json(details), migration_key),
            )
        return LegacyMigrationResult(
            status="completed",
            meal_rows=len(meals),
            meal_groups=len(groups),
            workout_rows=len(workouts),
            backup_path=str(backup_path),
            backup_checksum=backup_checksum,
        )

    def _record_failure(
        self,
        user_id: str,
        migration_key: str,
        source_checksum: str,
        backup_path: str | None,
        backup_checksum: str | None,
        error_code: str,
    ) -> None:
        details = {"error_code": error_code}
        if backup_checksum:
            details["backup_checksum"] = backup_checksum
        try:
            with self.database.transaction() as connection:
                completed = connection.execute(
                    "SELECT status FROM data_migrations WHERE migration_key = ?",
                    (migration_key,),
                ).fetchone()
                if completed is not None and completed["status"] == "completed":
                    return
                connection.execute(
                    """
                    INSERT INTO data_migrations (
                        migration_key, user_id, checksum, status,
                        source_backup_path, details_json, started_at, completed_at
                    ) VALUES (?, ?, ?, 'failed', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ON CONFLICT(migration_key) DO UPDATE SET
                        user_id = excluded.user_id,
                        checksum = excluded.checksum,
                        status = 'failed',
                        source_backup_path = excluded.source_backup_path,
                        details_json = excluded.details_json,
                        completed_at = CURRENT_TIMESTAMP
                    """,
                    (
                        migration_key, user_id, source_checksum, backup_path,
                        _json(details),
                    ),
                )
        except sqlite3.Error:
            return

    def _ledger(self, migration_key: str):
        with self.database.connection() as connection:
            return connection.execute(
                "SELECT * FROM data_migrations WHERE migration_key = ?",
                (migration_key,),
            ).fetchone()

    def _user_root(self, user_id: str) -> Path:
        if not isinstance(user_id, str) or _SAFE_USER_ID.fullmatch(user_id) is None:
            raise LegacyMigrationError("LEGACY_USER_ID_INVALID")
        users_root = (self.data_dir / "users").resolve(strict=False)
        user_root = (users_root / user_id).resolve(strict=False)
        if user_root.parent != users_root:
            raise LegacyMigrationError("LEGACY_USER_ID_INVALID")
        return user_root


def _read_source(path: Path, required_headers: tuple[str, ...]) -> bytes:
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        content = (",".join(required_headers) + "\n").encode("utf-8")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise LegacyMigrationError("LEGACY_CSV_ENCODING_INVALID") from None
    reader = csv.DictReader(io.StringIO(text, newline=""))
    headers = tuple(reader.fieldnames or ())
    if not set(required_headers).issubset(headers):
        raise LegacyMigrationError("LEGACY_CSV_HEADERS_INVALID")
    list(reader)
    return content


def _rows(content: bytes, required_headers: tuple[str, ...]):
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline=""))
    if not set(required_headers).issubset(reader.fieldnames or ()):
        raise LegacyMigrationError("LEGACY_CSV_HEADERS_INVALID")
    for index, raw in enumerate(reader, start=1):
        if None in raw:
            raise LegacyMigrationError("LEGACY_CSV_ROW_INVALID")
        yield index, {str(key): (value or "").strip() for key, value in raw.items()}


def _parse_meals(content: bytes) -> tuple[_MealRow, ...]:
    output = []
    for index, raw in _rows(content, MEAL_HEADERS):
        log_date = _date(raw["date"])
        meal = _required(raw["meal"], "LEGACY_MEAL_LABEL_REQUIRED")
        food = _required(raw["food"], "LEGACY_FOOD_REQUIRED")
        amount, unit = _amount(raw["amount"])
        source_id = _row_source_id("meal", index, raw)
        output.append(
            _MealRow(
                source_id, log_date, meal, food, amount, unit,
                _number(raw["calories"]), _number(raw["protein"]),
                _number(raw["carbs"]), _number(raw["fat"]), raw,
            )
        )
    return tuple(output)


def _parse_workouts(content: bytes) -> tuple[_WorkoutRow, ...]:
    output = []
    for index, raw in _rows(content, WORKOUT_HEADERS):
        workout_type = _required(raw["type"], "LEGACY_WORKOUT_TYPE_REQUIRED")
        normalized_type = workout_type.casefold()
        if normalized_type in {"strength", "resistance", "力量", "力量训练"}:
            kind = "strength"
        elif normalized_type in {"cardio", "aerobic", "有氧", "有氧训练"}:
            kind = "cardio"
        else:
            kind = "unknown"
        sets = _optional_integer(raw["sets"], maximum=100)
        reps = _optional_integer(raw["reps"], maximum=1000)
        output.append(
            _WorkoutRow(
                _row_source_id("workout", index, raw), _date(raw["date"]),
                kind, raw["exercise"], raw["muscle_group"] or None,
                sets, reps, _optional_number(raw["weight"]),
                _optional_number(raw["duration_min"], positive=True), raw,
            )
        )
    return tuple(output)


def _group_meals(meals: tuple[_MealRow, ...]):
    groups: dict[tuple[str, str], list[_MealRow]] = {}
    for row in meals:
        groups.setdefault((row.log_date, row.meal_label), []).append(row)
    return tuple((identity, tuple(rows)) for identity, rows in groups.items())


def _insert_meals(connection, user_id: str, groups) -> None:
    next_position: dict[str, int] = {}
    for (log_date, label), rows in groups:
        if log_date not in next_position:
            current = connection.execute(
                "SELECT COALESCE(MAX(position), 0) AS position FROM meals WHERE user_id = ? AND log_date = ?",
                (user_id, log_date),
            ).fetchone()["position"]
            next_position[log_date] = int(current) + 1
        group_source_id = _identity("meal-group", user_id, log_date, label)
        meal_id = _identity("meal", user_id, group_source_id)
        connection.execute(
            """
            INSERT INTO meals (
                id, user_id, log_date, name, meal_type, position,
                entry_method, legacy_source_id
            ) VALUES (?, ?, ?, ?, ?, ?, 'legacy', ?)
            """,
            (
                meal_id, user_id, log_date, label, label,
                next_position[log_date], f"{MIGRATION_VERSION}:{group_source_id}",
            ),
        )
        next_position[log_date] += 1
        for row in rows:
            connection.execute(
                """
                INSERT INTO meal_items (
                    id, meal_id, food_name, amount, unit, basis_type,
                    calories, carbs, protein, fat, source,
                    provenance_json
                ) VALUES (?, ?, ?, ?, ?, 'per_serving', ?, ?, ?, ?,
                          'legacy_import', ?)
                """,
                (
                    _identity("meal-item", user_id, row.source_id), meal_id,
                    row.food, row.amount, row.unit, row.calories, row.carbs,
                    row.protein, row.fat,
                    _json({"legacy_source_id": row.source_id, "raw": row.raw}),
                ),
            )


def _insert_workouts(
    connection, user_id: str, workouts: tuple[_WorkoutRow, ...]
) -> None:
    for row in workouts:
        session_id = _identity("training-session", user_id, row.source_id)
        title = row.exercise or row.raw["type"] or "Legacy workout"
        provenance = {"legacy_source_id": row.source_id, "raw": row.raw}
        connection.execute(
            """
            INSERT INTO training_sessions (
                id, user_id, log_date, title, duration_min, entry_method,
                estimate_json, legacy_source_id
            ) VALUES (?, ?, ?, ?, ?, 'legacy', ?, ?)
            """,
            (
                session_id, user_id, row.log_date, title, row.duration_min,
                _json({"legacy_provenance": provenance}),
                f"{MIGRATION_VERSION}:{row.source_id}",
            ),
        )
        if row.workout_type == "strength" and row.exercise:
            exercise_id = _identity("strength-exercise", user_id, row.source_id)
            connection.execute(
                """
                INSERT INTO strength_exercises (
                    id, session_id, exercise_name, primary_muscle,
                    provenance_json, position
                ) VALUES (?, ?, ?, ?, ?, 1)
                """,
                (
                    exercise_id, session_id, row.exercise,
                    row.muscle_group or "unspecified", _json(provenance),
                ),
            )
            if row.sets is not None and row.reps is not None and row.reps > 0:
                for number in range(1, row.sets + 1):
                    connection.execute(
                        """
                        INSERT INTO strength_sets (
                            id, strength_exercise_id, set_number, reps,
                            load_kg, bodyweight
                        ) VALUES (?, ?, ?, ?, ?, 0)
                        """,
                        (
                            _identity("strength-set", user_id, row.source_id, str(number)),
                            exercise_id, number, row.reps, row.weight,
                        ),
                    )
        elif row.workout_type == "cardio" and row.exercise and row.duration_min:
            connection.execute(
                """
                INSERT INTO cardio_items (
                    id, session_id, activity_name, duration_min,
                    estimate_json, provenance_json, position
                ) VALUES (?, ?, ?, ?, '{}', ?, 1)
                """,
                (
                    _identity("cardio-item", user_id, row.source_id),
                    session_id, row.exercise, row.duration_min,
                    _json(provenance),
                ),
            )


def _reconcile(connection, user_id: str, meals, groups, workouts) -> None:
    prefix = f"{MIGRATION_VERSION}:%"
    meal = connection.execute(
        """
        SELECT COUNT(DISTINCT meals.id) AS groups,
               COUNT(meal_items.id) AS rows,
               COALESCE(SUM(meal_items.calories), 0) AS calories,
               COALESCE(SUM(meal_items.protein), 0) AS protein,
               COALESCE(SUM(meal_items.carbs), 0) AS carbs,
               COALESCE(SUM(meal_items.fat), 0) AS fat,
               MIN(meals.log_date) AS min_date, MAX(meals.log_date) AS max_date
        FROM meals LEFT JOIN meal_items ON meal_items.meal_id = meals.id
        WHERE meals.user_id = ? AND meals.legacy_source_id LIKE ?
        """,
        (user_id, prefix),
    ).fetchone()
    workout = connection.execute(
        """
        SELECT COUNT(*) AS rows, COALESCE(SUM(duration_min), 0) AS duration,
               MIN(log_date) AS min_date, MAX(log_date) AS max_date
        FROM training_sessions
        WHERE user_id = ? AND legacy_source_id LIKE ?
        """,
        (user_id, prefix),
    ).fetchone()
    expected_meal_totals = (
        sum(row.calories for row in meals), sum(row.protein for row in meals),
        sum(row.carbs for row in meals), sum(row.fat for row in meals),
    )
    actual_meal_totals = tuple(meal[key] for key in ("calories", "protein", "carbs", "fat"))
    meal_dates = [row.log_date for row in meals]
    workout_dates = [row.log_date for row in workouts]
    valid = (
        meal["groups"] == len(groups)
        and meal["rows"] == len(meals)
        and all(abs(actual - expected) < 1e-6 for actual, expected in zip(actual_meal_totals, expected_meal_totals))
        and workout["rows"] == len(workouts)
        and abs(workout["duration"] - sum(row.duration_min or 0 for row in workouts)) < 1e-6
        and (meal["min_date"], meal["max_date"]) == _bounds(meal_dates)
        and (workout["min_date"], workout["max_date"]) == _bounds(workout_dates)
    )
    if not valid:
        raise LegacyMigrationError("LEGACY_RECONCILIATION_FAILED")


def _create_backup(
    user_root: Path,
    *,
    user_id: str,
    migration_key: str,
    sources: dict[str, bytes],
    source_checksum: str,
) -> tuple[Path, str]:
    backup_root = user_root / "legacy-backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = backup_root / f"{MIGRATION_VERSION}-{timestamp}-{source_checksum[:12]}.zip"
    manifest = {
        "migration_key": migration_key,
        "user_id": user_id,
        "source_checksum": source_checksum,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": {
            name: {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            for name, content in sorted(sources.items())
        },
    }
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(sources.items()):
            archive.writestr(name, content)
        archive.writestr("manifest.json", _json(manifest).encode("utf-8"))
    checksum = hashlib.sha256(target.read_bytes()).hexdigest()
    os.chmod(target, stat.S_IREAD)
    return target, checksum


def _source_checksum(sources: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, content in sorted(sources.items()):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def _row_source_id(kind: str, index: int, raw: dict[str, str]) -> str:
    return hashlib.sha256(
        _json({"kind": kind, "row": index, "values": raw}).encode("utf-8")
    ).hexdigest()


def _identity(*parts: str) -> str:
    return uuid5(NAMESPACE_URL, ":".join(parts)).hex


def _date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except (TypeError, ValueError):
        raise LegacyMigrationError("LEGACY_DATE_INVALID") from None


def _required(value: str, code: str) -> str:
    if not value:
        raise LegacyMigrationError(code)
    return value


def _number(value: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise LegacyMigrationError("LEGACY_NUMBER_INVALID") from None
    if number < 0 or number != number or number in (float("inf"), float("-inf")):
        raise LegacyMigrationError("LEGACY_NUMBER_INVALID")
    return number


def _optional_number(value: str, *, positive: bool = False) -> float | None:
    if not value:
        return None
    number = _number(value)
    if positive and number == 0:
        return None
    return number


def _optional_integer(value: str, *, maximum: int) -> int | None:
    number = _optional_number(value)
    if number is None or number == 0:
        return None
    if not number.is_integer() or number > maximum:
        raise LegacyMigrationError("LEGACY_INTEGER_INVALID")
    return int(number)


def _amount(value: str) -> tuple[float, str]:
    matched = _AMOUNT.fullmatch(value)
    if matched is None:
        return 1.0, "legacy_entry"
    amount = _number(matched.group(1))
    if amount <= 0:
        raise LegacyMigrationError("LEGACY_AMOUNT_INVALID")
    return amount, matched.group(2) or "serving"


def _bounds(values: list[str]) -> tuple[str | None, str | None]:
    return (min(values), max(values)) if values else (None, None)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_object(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
