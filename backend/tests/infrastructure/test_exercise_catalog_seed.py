from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from backend.application.ports.workout_repository import (
    StrengthExerciseInput,
    WorkoutDraftInput,
)
from backend.domain.workouts import StrengthSet
from backend.infrastructure.catalog.seed_exercises import seed_bundled_exercises
from backend.infrastructure.repositories.sqlite_exercise_catalog_repository import (
    SQLiteExerciseCatalogRepository,
)
from backend.infrastructure.repositories.sqlite_workout_repository import (
    SQLiteWorkoutRepository,
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
    squat = next(
        item
        for item in repository.search("user-a", "杠铃全深蹲", limit=20)
        if item.source_record_id == "Barbell_Full_Squat"
    )
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


def test_localized_reimport_preserves_ids_and_historical_workout_names(
    tmp_path: Path,
) -> None:
    localized = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    legacy = json.loads(json.dumps(localized, ensure_ascii=False))
    legacy["dataset_version"] = "2026-08-08"
    for record in legacy["exercises"]:
        record["dataset_version"] = "2026-08-08"
    legacy_squat = next(
        record
        for record in legacy["exercises"]
        if record["source_record_id"] == "Barbell_Full_Squat"
    )
    legacy_squat["name"] = "杠铃深蹲"
    legacy_squat["primary_muscle"] = "quadriceps"
    legacy_squat["secondary_muscles"] = [
        "calves",
        "glutes",
        "hamstrings",
        "lower back",
    ]
    legacy_squat["provenance"].pop("localization", None)
    legacy_squat["provenance"].pop("upstream", None)
    legacy_squat["provenance"]["profile"] = "free-exercise-db@1.0.0"
    legacy_path = tmp_path / "exercises.legacy.json"
    legacy_path.write_text(
        json.dumps(legacy, ensure_ascii=False),
        encoding="utf-8",
    )

    database = _database(tmp_path)
    seed_bundled_exercises(database, legacy_path)
    catalog = SQLiteExerciseCatalogRepository(database)
    old_squat = next(
        item
        for item in catalog.search("user-a", "杠铃深蹲", limit=20)
        if item.source_record_id == "Barbell_Full_Squat"
    )
    old_ids = _public_exercise_ids(database)
    _insert_profile(database)
    workouts = SQLiteWorkoutRepository(
        database,
        clock=lambda: datetime(2026, 8, 15, tzinfo=timezone.utc),
    )
    draft = workouts.create_draft(
        "user-a",
        WorkoutDraftInput(
            log_date="2026-08-15",
            title="腿部训练",
            started_at=None,
            duration_min=30,
            intensity="medium",
            entry_method="form",
            strength_exercises=(
                StrengthExerciseInput(
                    catalog_exercise_id=old_squat.id,
                    sets=(StrengthSet(1, 8, 60, False),),
                ),
            ),
            cardio_items=(),
        ),
        expires_at="2026-09-15T00:00:00Z",
    )
    workouts.confirm(
        "user-a",
        draft.id,
        expected_version=draft.version,
        idempotency_key="legacy-squat",
        request_fingerprint="legacy-squat",
    )

    result = seed_bundled_exercises(database, SEED_PATH)

    assert result.updated_count == EXPECTED_COUNT
    assert _public_exercise_ids(database) == old_ids
    localized_squat = next(
        item
        for item in catalog.search("user-a", "杠铃深蹲", limit=20)
        if item.source_record_id == "Barbell_Full_Squat"
    )
    assert localized_squat.id == old_squat.id
    assert localized_squat.name == "杠铃全深蹲"
    assert "Barbell Full Squat" in localized_squat.aliases
    assert any(
        alias.startswith("杠铃深蹲") for alias in localized_squat.aliases
    )
    assert localized_squat.primary_muscle == "股四头肌"
    assert localized_squat.provenance["localization"]["equipment"] == "杠铃"
    assert localized_squat.provenance["localization"]["category"] == "力量训练"
    assert next(
        item
        for item in catalog.search("user-a", "Barbell Full Squat", limit=20)
        if item.source_record_id == "Barbell_Full_Squat"
    ).id == old_squat.id
    assert (
        workouts.list_sessions("user-a", "2026-08-15")[0]
        .strength_exercises[0]
        .exercise_name
        == "杠铃深蹲"
    )


def _public_exercise_ids(database: SQLiteDatabase) -> dict[str, str]:
    with database.connection() as connection:
        rows = connection.execute(
            """
            SELECT source_record_id, id
            FROM exercise_catalog
            WHERE owner_user_id IS NULL
            """
        ).fetchall()
    return {row["source_record_id"]: row["id"] for row in rows}


def _insert_profile(database: SQLiteDatabase) -> None:
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO user_profile_versions (
                id, user_id, age, height_cm, weight_kg, energy_parameter,
                activity_level, auto_target_disabled, safety_conditions_json,
                effective_from, created_at
            ) VALUES (
                'profile-a', 'user-a', 30, 175, 70, 'neutral',
                'moderate', 0, '[]', '2026-01-01T00:00:00Z',
                '2026-01-01T00:00:00Z'
            )
            """
        )


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
