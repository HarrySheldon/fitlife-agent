from __future__ import annotations

import hashlib
import json
import os
import stat
import zipfile
from pathlib import Path

from backend.infrastructure.migration.legacy_csv import LegacyCsvMigrator
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


USER_ID = "a" * 32
MEALS = b"""date,meal,food,amount,calories,protein,carbs,fat,notes
2026-07-20,Breakfast,Oats,100g,379,13.2,67.7,6.52,raw note
2026-07-20,Breakfast,Egg,2 serving,155,12.6,1.12,10.6,
2026-07-21,Dinner,Unknown bowl,one bowl,500,30,50,20,keep me
"""
WORKOUTS = b"""date,type,exercise,muscle_group,sets,reps,weight,duration_min,notes
2026-07-20,strength,Squat,legs,3,8,60,45,known strength
2026-07-21,cardio,Running,,,,,30,known cardio
2026-07-22,mobility,Stretching,,,,,,unknown kind
"""


def _setup(tmp_path: Path):
    data_dir = tmp_path / "data"
    root = data_dir / "users" / USER_ID
    root.mkdir(parents=True)
    (root / "meals.csv").write_bytes(MEALS)
    (root / "workouts.csv").write_bytes(WORKOUTS)
    database = SQLiteDatabase(data_dir / "fitlife.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    return data_dir, root, database


def test_migration_archives_exact_sources_groups_meals_and_reconciles(tmp_path):
    data_dir, root, database = _setup(tmp_path)

    result = LegacyCsvMigrator(database, data_dir).migrate_user(USER_ID)

    assert result.status == "completed"
    assert (result.meal_rows, result.meal_groups, result.workout_rows) == (3, 2, 3)
    assert (root / "meals.csv").read_bytes() == MEALS
    assert (root / "workouts.csv").read_bytes() == WORKOUTS
    backup = Path(result.backup_path)
    assert backup.parent == root / "legacy-backups"
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == result.backup_checksum
    assert not os.stat(backup).st_mode & stat.S_IWRITE
    with zipfile.ZipFile(backup) as archive:
        assert archive.read("meals.csv") == MEALS
        assert archive.read("workouts.csv") == WORKOUTS
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["user_id"] == USER_ID
    assert manifest["files"]["meals.csv"]["sha256"] == hashlib.sha256(MEALS).hexdigest()

    with database.connection() as connection:
        meal_rows = connection.execute(
            "SELECT log_date, name, position FROM meals ORDER BY log_date, position"
        ).fetchall()
        totals = connection.execute(
            "SELECT COUNT(*) AS count, SUM(calories) AS calories, SUM(protein) AS protein, SUM(carbs) AS carbs, SUM(fat) AS fat FROM meal_items"
        ).fetchone()
        sessions = connection.execute(
            "SELECT log_date, title, duration_min, estimate_json FROM training_sessions ORDER BY log_date"
        ).fetchall()
        sets = connection.execute(
            "SELECT set_number, reps, load_kg FROM strength_sets ORDER BY set_number"
        ).fetchall()
        cardio = connection.execute("SELECT activity_name, duration_min FROM cardio_items").fetchone()
        ledger = connection.execute(
            "SELECT user_id, status, details_json FROM data_migrations"
        ).fetchone()
    assert [tuple(row) for row in meal_rows] == [
        ("2026-07-20", "Breakfast", 1),
        ("2026-07-21", "Dinner", 1),
    ]
    assert totals["count"] == 3
    assert tuple(round(totals[key], 2) for key in ("calories", "protein", "carbs", "fat")) == (
        1034.0, 55.8, 118.82, 37.12,
    )
    assert len(sessions) == 3
    assert [row["duration_min"] for row in sessions] == [45.0, 30.0, None]
    assert "unknown kind" in sessions[2]["estimate_json"]
    assert [tuple(row) for row in sets] == [(1, 8, 60.0), (2, 8, 60.0), (3, 8, 60.0)]
    assert tuple(cardio) == ("Running", 30.0)
    assert ledger["user_id"] == USER_ID
    assert ledger["status"] == "completed"
    assert json.loads(ledger["details_json"])["meal_rows"] == 3


def test_completed_migration_is_sticky_when_legacy_files_drift(tmp_path):
    data_dir, root, database = _setup(tmp_path)
    migrator = LegacyCsvMigrator(database, data_dir)
    first = migrator.migrate_user(USER_ID)
    (root / "meals.csv").write_bytes(MEALS.replace(b"379", b"999"))

    replay = migrator.migrate_user(USER_ID)

    assert replay.status == "skipped"
    assert replay.backup_checksum == first.backup_checksum
    with database.connection() as connection:
        assert connection.execute("SELECT SUM(calories) FROM meal_items").fetchone()[0] == 1034


def test_invalid_csv_records_safe_failure_without_mutating_sources(tmp_path):
    data_dir, root, database = _setup(tmp_path)
    invalid = MEALS.replace(b"379", b"-1")
    (root / "meals.csv").write_bytes(invalid)

    result = LegacyCsvMigrator(database, data_dir).migrate_user(USER_ID)

    assert result.status == "failed"
    assert result.error_code == "LEGACY_NUMBER_INVALID"
    assert (root / "meals.csv").read_bytes() == invalid
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM meals").fetchone()[0] == 0
        ledger = connection.execute("SELECT status, details_json FROM data_migrations").fetchone()
    assert ledger["status"] == "failed"
    assert "-1" not in ledger["details_json"]


def test_write_failure_rolls_back_formal_rows_and_can_retry(tmp_path):
    data_dir, _, database = _setup(tmp_path)
    with database.transaction() as connection:
        connection.execute(
            "CREATE TRIGGER reject_legacy_meal BEFORE INSERT ON meal_items BEGIN SELECT RAISE(ABORT, 'private row'); END"
        )
    migrator = LegacyCsvMigrator(database, data_dir)

    failed = migrator.migrate_user(USER_ID)

    assert failed.status == "failed"
    assert failed.error_code == "LEGACY_MIGRATION_FAILED"
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM meals").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM training_sessions").fetchone()[0] == 0
    with database.transaction() as connection:
        connection.execute("DROP TRIGGER reject_legacy_meal")

    retried = migrator.migrate_user(USER_ID)
    assert retried.status == "completed"
