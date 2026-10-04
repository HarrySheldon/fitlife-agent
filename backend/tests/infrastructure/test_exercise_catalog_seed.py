from __future__ import annotations

import json
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from backend.application.ports.exercise_catalog_repository import ExerciseCatalogItem
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
LEGACY_SEARCH_TERMS_PATH = (
    Path(__file__).parents[2] / "data" / "catalog" / "legacy-search-terms.v1.json"
)
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
    full_squat_zh = _search_by_source_id(
        repository, "杠铃深蹲", "Barbell_Full_Squat"
    )
    full_squat_en = _search_by_source_id(
        repository, "Barbell Full Squat", "Barbell_Full_Squat"
    )
    standard_squat_zh = _search_by_source_id(
        repository, "杠铃标准深蹲", "Barbell_Squat"
    )
    standard_squat_en = _search_by_source_id(
        repository, "Barbell Squat", "Barbell_Squat"
    )
    running = next(
        item
        for item in repository.search("user-a", "Running Treadmill", limit=50)
        if item.source_record_id == "Running_Treadmill"
    )
    assert full_squat_zh.name == full_squat_en.name == "杠铃深蹲"
    assert standard_squat_zh.name == standard_squat_en.name == "杠铃标准深蹲"
    assert full_squat_zh.license == "Unlicense"
    assert running.exercise_type == "cardio"
    assert running.met is None
    assert len(full_squat_zh.content_hash or "") == 64


def test_seed_preserves_explicit_legacy_exercise_search_terms(tmp_path: Path) -> None:
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    legacy = json.loads(LEGACY_SEARCH_TERMS_PATH.read_text(encoding="utf-8"))[
        "exercises"
    ]
    records = {
        record["source_record_id"]: record for record in payload["exercises"]
    }

    for source_id, terms in legacy.items():
        record = records[source_id]
        available = {
            unicodedata.normalize("NFKC", term).casefold()
            for term in (record["name"], *record["aliases"])
        }
        assert {
            unicodedata.normalize("NFKC", term).casefold() for term in terms
        } <= available

    database = _database(tmp_path)
    seed_bundled_exercises(database, SEED_PATH)
    with database.connection() as connection:
        seeded = {
            (row["source_record_id"], row["normalized_alias"])
            for row in connection.execute(
                """
                SELECT exercise.source_record_id, alias.normalized_alias
                FROM catalog_aliases AS alias
                JOIN exercise_catalog AS exercise ON exercise.id = alias.exercise_id
                """
            )
        }
    expected = {
        (source_id, unicodedata.normalize("NFKC", term).casefold())
        for source_id, terms in legacy.items()
        for term in terms
    }
    assert expected <= seeded


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
    legacy_squat["name"] = "杠铃全深蹲"
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
    legacy_standard_squat = next(
        record
        for record in legacy["exercises"]
        if record["source_record_id"] == "Barbell_Squat"
    )
    legacy_standard_squat["name"] = "杠铃深蹲"
    legacy_standard_squat["aliases"] = [
        "Barbell Squat",
        "杠铃后蹲",
        "gang ling shen dun",
    ]
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
        for item in catalog.search("user-a", "杠铃全深蹲", limit=20)
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
    assert localized_squat.name == "杠铃深蹲"
    assert "Barbell Full Squat" in localized_squat.aliases
    assert {"杠铃全蹲", "杠铃深蹲到底", "杠铃全深蹲"} <= set(
        localized_squat.aliases
    )
    assert localized_squat.primary_muscle == "股四头肌"
    assert localized_squat.provenance["localization"]["equipment"] == "杠铃"
    assert localized_squat.provenance["localization"]["category"] == "力量训练"
    assert next(
        item
        for item in catalog.search("user-a", "Barbell Full Squat", limit=20)
        if item.source_record_id == "Barbell_Full_Squat"
    ).id == old_squat.id
    assert _search_by_source_id(
        catalog, "杠铃标准深蹲", "Barbell_Squat"
    ).name == "杠铃标准深蹲"
    assert _search_by_source_id(
        catalog, "Barbell Squat", "Barbell_Squat"
    ).name == "杠铃标准深蹲"
    assert (
        workouts.list_sessions("user-a", "2026-08-15")[0]
        .strength_exercises[0]
        .exercise_name
        == "杠铃全深蹲"
    )


def _search_by_source_id(
    repository: SQLiteExerciseCatalogRepository,
    query: str,
    source_record_id: str,
) -> ExerciseCatalogItem:
    results = repository.search("user-a", query, limit=50)
    assert results
    assert results[0].source_record_id == source_record_id
    return results[0]


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
