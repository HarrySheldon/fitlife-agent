from __future__ import annotations

import json
from pathlib import Path

from backend.infrastructure.catalog.seed_exercises import seed_bundled_exercises
from backend.infrastructure.repositories.sqlite_exercise_catalog_repository import (
    SQLiteExerciseCatalogRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


SEED_PATH = Path(__file__).parents[2] / "data" / "catalog" / "exercises.zh-CN.v1.json"
EXPECTED_COUNT = 750


def _database(tmp_path: Path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "exercise-seed.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    return database


def test_seed_is_auditable_idempotent_and_searchable(tmp_path: Path) -> None:
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    assert len(payload["exercises"]) == EXPECTED_COUNT
    assert payload["dataset_version"] == "2026-08-09"
    assert payload["managed_sources"] == ["free-exercise-db"]
    assert {item["exercise_type"] for item in payload["exercises"]} == {"strength", "cardio"}
    assert all(item["source_name"] == "free-exercise-db" for item in payload["exercises"])
    assert all(item["provenance"]["original_category"] != "stretching" for item in payload["exercises"])

    database = _database(tmp_path)
    first = seed_bundled_exercises(database, SEED_PATH)
    second = seed_bundled_exercises(database, SEED_PATH)

    assert first.inserted_count == EXPECTED_COUNT
    assert second.unchanged_count == EXPECTED_COUNT
    repository = SQLiteExerciseCatalogRepository(database)
    squat = repository.search("user-a", "深蹲", limit=20)[0]
    running = next(
        item
        for item in repository.search("user-a", "Running Treadmill", limit=50)
        if item.source_record_id == "Running_Treadmill"
    )
    assert squat.source_record_id == "Barbell_Full_Squat"
    assert squat.license == "Unlicense"
    assert running.exercise_type == "cardio"
    assert running.met is None
    assert len(squat.content_hash or "") == 64


def test_removed_seed_records_are_deactivated(tmp_path: Path) -> None:
    database = _database(tmp_path)
    seed_bundled_exercises(database, SEED_PATH)
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    payload["dataset_version"] = "2026-08-10"
    payload["exercises"] = []
    removed = tmp_path / "removed-exercises.json"
    removed.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = seed_bundled_exercises(database, removed)

    assert result.deactivated_count == EXPECTED_COUNT
    assert SQLiteExerciseCatalogRepository(database).search("user-a", "深蹲", limit=20) == ()
