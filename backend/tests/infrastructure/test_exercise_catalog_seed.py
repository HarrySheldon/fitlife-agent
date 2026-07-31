from __future__ import annotations

import json
from pathlib import Path

from backend.infrastructure.catalog.seed_exercises import (
    seed_bundled_exercises,
)
from backend.infrastructure.repositories.sqlite_exercise_catalog_repository import (
    SQLiteExerciseCatalogRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


SEED_PATH = (
    Path(__file__).parents[2]
    / "data"
    / "catalog"
    / "exercises.zh-CN.v1.json"
)


def _database(tmp_path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "exercise-seed.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    return database


def test_seed_is_auditable_idempotent_and_searchable(tmp_path):
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    assert len(payload["exercises"]) == 10
    assert payload["dataset_version"] == "2026-07-25"
    assert {
        item["exercise_type"] for item in payload["exercises"]
    } == {"strength", "cardio"}
    for item in payload["exercises"]:
        assert item["source_name"]
        assert item["source_record_id"]
        assert item["dataset_version"] == "2026-07-25"
        assert item["attribution"]
        assert item["provenance"]["source_url"].startswith("https://")

    database = _database(tmp_path)
    first = seed_bundled_exercises(database, SEED_PATH)
    second = seed_bundled_exercises(database, SEED_PATH)

    assert first.inserted_count == 10
    assert second.unchanged_count == 10
    repository = SQLiteExerciseCatalogRepository(database)
    squat = repository.search("user-a", "squat", limit=20)[0]
    running = repository.search("user-a", "running", limit=20)[0]
    assert squat.source_record_id == "Barbell_Full_Squat"
    assert squat.license == "Unlicense"
    assert running.exercise_type == "cardio"
    assert running.met == 9.8
    assert len(squat.content_hash or "") == 64


def test_removed_seed_records_are_deactivated(tmp_path):
    database = _database(tmp_path)
    seed_bundled_exercises(database, SEED_PATH)
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    payload["dataset_version"] = "2026-07-26"
    payload["exercises"] = []
    removed = tmp_path / "removed-exercises.json"
    removed.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = seed_bundled_exercises(database, removed)

    assert result.deactivated_count == 10
    assert SQLiteExerciseCatalogRepository(database).search(
        "user-a",
        "squat",
        limit=20,
    ) == ()
