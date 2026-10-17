from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from backend.application.ports.exercise_catalog_repository import (
    ExerciseDefinition,
    NewCustomExercise,
)
from backend.application.ports.food_catalog_repository import NewCustomFood
from backend.application.ports.meal_repository import MealDraftInput, MealDraftItemInput
from backend.application.ports.workout_repository import (
    StrengthExerciseInput,
    WorkoutDraftInput,
)
from backend.domain.meals import FoodDefinition
from backend.domain.workouts import StrengthSet
from backend.infrastructure.catalog.import_ledger import CatalogImportError
from backend.infrastructure.catalog.seed_exercises import seed_exercise_payload
from backend.infrastructure.catalog.seed_foods import seed_food_payload
from backend.infrastructure.repositories.sqlite_exercise_catalog_repository import (
    SQLiteExerciseCatalogRepository,
)
from backend.infrastructure.repositories.sqlite_food_catalog_repository import (
    SQLiteFoodCatalogRepository,
)
from backend.infrastructure.repositories.sqlite_meal_repository import SQLiteMealRepository
from backend.infrastructure.repositories.sqlite_workout_repository import (
    SQLiteWorkoutRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


def _payload(kind):
    metadata = dict(
        source_name=f"synthetic-public-{kind}",
        dataset_version="upstream-v1",
        license="CC0",
        attribution="Synthetic test",
    )
    record = dict(
        metadata,
        source_record_id="record-1",
        name="Original",
        aliases=["original-alias"],
        provenance={"test": True},
    )
    if kind == "food":
        record.update(
            basis_type="per_100g", basis_amount=100, unit="g",
            calories=100, carbs=10, protein=5, fat=3,
        )
        return dict(metadata, schema_version=1, foods=[record])
    record.update(
        exercise_type="strength", primary_muscle="legs",
        secondary_muscles=[], met=None,
    )
    return dict(
        schema_version=1, dataset_version="upstream-v1",
        managed_sources=[metadata["source_name"]], exercises=[record],
    )


def _database(tmp_path):
    database = SQLiteDatabase(tmp_path / "release.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    return database


def _rows(database, table):
    with database.connection() as connection:
        return tuple(
            tuple(row)
            for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")
        )


def _catalog_state(database):
    return {
        table: _rows(database, table)
        for table in (
            "food_catalog", "exercise_catalog", "catalog_aliases",
            "catalog_search", "catalog_imports",
        )
    }


def test_release_key_is_structural_and_legacy_version_is_exact():
    from backend.infrastructure.catalog.release import catalog_import_version

    assert catalog_import_version({}, " upstream-v1 ") == " upstream-v1 "
    first = catalog_import_version({"catalog_release": "v1"}, "upstream-v1")
    assert first.startswith("catalog-release:")
    assert json.loads(first.removeprefix("catalog-release:")) == ["upstream-v1", "v1"]
    assert first != catalog_import_version({"catalog_release": "v1"}, "other")
    assert catalog_import_version(
        {"catalog_release": "b-c"}, "a"
    ) != catalog_import_version({"catalog_release": "c"}, "a-b")
    with pytest.raises(ValueError, match="^CATALOG_RELEASE_INVALID$"):
        catalog_import_version({"catalog_release": "v2"}, first)
    assert catalog_import_version({}, first) == first


@pytest.mark.parametrize("release", ["a", "a" * 64, "Z0._-v1"])
def test_valid_release_boundaries(release):
    from backend.infrastructure.catalog.release import catalog_import_version

    key = catalog_import_version({"catalog_release": release}, "upstream-v1")
    assert json.loads(key.removeprefix("catalog-release:")) == [
        "upstream-v1", release,
    ]


@pytest.mark.parametrize(
    "kind,seed", [("food", seed_food_payload), ("exercise", seed_exercise_payload)]
)
def test_completed_legacy_key_collision_fails_closed(tmp_path, kind, seed):
    from backend.infrastructure.catalog.release import catalog_import_version

    database = _database(tmp_path)
    payload = _payload(kind)
    payload["catalog_release"] = "v1"
    qualified = catalog_import_version(payload, "upstream-v1")
    legacy = deepcopy(payload)
    del legacy["catalog_release"]
    legacy["dataset_version"] = qualified
    legacy[f"{kind}s"][0]["dataset_version"] = qualified
    seed(database, legacy)
    before = _catalog_state(database)

    with pytest.raises(CatalogImportError, match="CATALOG_IMPORT_CHECKSUM_MISMATCH"):
        seed(database, payload)

    assert _catalog_state(database) == before


@pytest.mark.parametrize(
    "kind,seed", [("food", seed_food_payload), ("exercise", seed_exercise_payload)]
)
def test_release_label_does_not_change_content_checksum(tmp_path, kind, seed):
    database = _database(tmp_path)
    payload = _payload(kind)
    seed(database, payload)
    payload["catalog_release"] = "v1"

    assert seed(database, payload).unchanged_count == 1

    with database.connection() as connection:
        checksums = connection.execute(
            "SELECT checksum FROM catalog_imports ORDER BY rowid"
        ).fetchall()
    assert len(checksums) == 2
    assert checksums[0]["checksum"] == checksums[1]["checksum"]


@pytest.mark.parametrize(
    "kind,seed", [("food", seed_food_payload), ("exercise", seed_exercise_payload)]
)
def test_explicit_release_preserves_legacy_ledger_ids_and_rejects_drift(
    tmp_path, kind, seed
):
    database = _database(tmp_path)
    payload = _payload(kind)
    assert seed(database, payload).inserted_count == 1
    original_ledger = _rows(database, "catalog_imports")[0]
    table = f"{kind}_catalog"
    with database.connection() as connection:
        original = dict(connection.execute(f"SELECT * FROM {table}").fetchone())
    assert seed(database, payload).skipped
    changed = deepcopy(payload)
    changed[f"{kind}s"][0]["name"] = "Localized"
    with pytest.raises(CatalogImportError, match="CATALOG_IMPORT_CHECKSUM_MISMATCH"):
        seed(database, changed)
    changed["catalog_release"] = "zh-CN.2026-10-17.1"
    assert seed(database, changed).updated_count == 1
    with database.connection() as connection:
        current = dict(connection.execute(f"SELECT * FROM {table}").fetchone())
    for field in (
        "id", "source_name", "source_record_id", "dataset_version", "provenance_json"
    ):
        assert current[field] == original[field]
    assert current["name"] == "Localized"
    with database.connection() as connection:
        assert connection.execute(
            "SELECT name FROM catalog_search WHERE catalog_id = ?",
            (original["id"],),
        ).fetchone()["name"] == "Localized"
    assert _rows(database, "catalog_imports")[0] == original_ledger
    assert seed(database, changed).skipped
    before = _catalog_state(database)
    changed[f"{kind}s"][0]["name"] = "Another localization"
    with pytest.raises(CatalogImportError, match="CATALOG_IMPORT_CHECKSUM_MISMATCH"):
        seed(database, changed)
    assert _catalog_state(database) == before
    changed["catalog_release"] = "zh-CN.2026-10-17.2"
    assert seed(database, changed).updated_count == 1
    assert len(_rows(database, "catalog_imports")) == 3
    assert _rows(database, "catalog_imports")[0] == original_ledger


@pytest.mark.parametrize(
    "release",
    [None, "", " ", " v1", "v1 ", True, False, 1, "a/b", "v1\n", "a" * 65, "_v1", "中文"],
)
@pytest.mark.parametrize(
    "kind,seed", [("food", seed_food_payload), ("exercise", seed_exercise_payload)]
)
def test_invalid_release_fails_before_any_mutation(tmp_path, kind, seed, release):
    database = _database(tmp_path)
    payload = _payload(kind)
    seed(database, payload)
    before = _catalog_state(database)
    payload["catalog_release"] = release
    payload[f"{kind}s"][0]["name"] = "Changed"
    with pytest.raises(ValueError, match="^CATALOG_RELEASE_INVALID$"):
        seed(database, payload)
    assert _catalog_state(database) == before


def test_release_preserves_private_rows_and_confirmed_meal_workout_snapshots(tmp_path):
    database = _database(tmp_path)
    foods, exercises = _payload("food"), _payload("exercise")
    seed_food_payload(database, foods)
    seed_exercise_payload(database, exercises)
    food_catalog = SQLiteFoodCatalogRepository(database)
    exercise_catalog = SQLiteExerciseCatalogRepository(database)
    food = food_catalog.search("user-a", "Original", limit=10)[0]
    exercise = exercise_catalog.search("user-a", "Original", limit=10)[0]
    private_food = food_catalog.create_custom_food(
        "user-a",
        NewCustomFood(
            FoodDefinition(
                name="Private food", basis_type="per_100g", basis_amount=100,
                unit="g", calories=80, carbs=2, protein=8, fat=4,
                source="user_custom",
            ),
            aliases=("Private food alias",),
        ),
    )
    private_exercise = exercise_catalog.create_custom_exercise(
        "user-a",
        NewCustomExercise(
            ExerciseDefinition(
                name="Private exercise", exercise_type="strength",
                primary_muscle="legs", secondary_muscles=(), met=None,
                source="user_custom",
            ),
            aliases=("Private exercise alias",),
        ),
    )
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO user_profile_versions (
                id, user_id, age, height_cm, weight_kg, energy_parameter,
                activity_level, auto_target_disabled, safety_conditions_json,
                effective_from, created_at
            ) VALUES (
                'profile-a', 'user-a', 30, 175, 70, 'neutral', 'moderate', 0,
                '[]', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            )
            """
        )

    def now():
        return datetime(2026, 8, 15, tzinfo=timezone.utc)

    meals = SQLiteMealRepository(database, clock=now)
    workouts = SQLiteWorkoutRepository(database, clock=now)
    meal = meals.create_draft(
        "user-a",
        MealDraftInput(
            log_date="2026-08-15", name="Lunch", meal_type="lunch",
            entry_method="form",
            items=(MealDraftItemInput(
                catalog_food_id=food.id, amount=100, unit="g",
            ),),
        ),
        expires_at="2026-09-15T00:00:00Z",
    )
    workout = workouts.create_draft(
        "user-a",
        WorkoutDraftInput(
            log_date="2026-08-15", title="Training", started_at=None,
            duration_min=30, intensity="medium", entry_method="form",
            strength_exercises=(StrengthExerciseInput(
                catalog_exercise_id=exercise.id,
                sets=(StrengthSet(1, 8, 60, False),),
            ),),
            cardio_items=(),
        ),
        expires_at="2026-09-15T00:00:00Z",
    )
    meals.confirm(
        "user-a", meal.id, expected_version=meal.version,
        idempotency_key="meal", request_fingerprint="meal",
    )
    workouts.confirm(
        "user-a", workout.id, expected_version=workout.version,
        idempotency_key="workout", request_fingerprint="workout",
    )
    old_meals = meals.list_meals("user-a", "2026-08-15")
    old_workouts = workouts.list_sessions("user-a", "2026-08-15")
    food_catalog.set_favorite("user-a", food.id, True)
    exercise_catalog.set_favorite("user-a", exercise.id, True)
    food_catalog.record_usage("user-a", food.id)
    exercise_catalog.record_usage("user-a", exercise.id)
    old_favorites = _rows(database, "catalog_favorites")
    old_usage = _rows(database, "catalog_usage")
    assert old_favorites and old_usage
    private_state = _private_state(database, private_food.id, private_exercise.id)
    for payload, kind, seed in (
        (foods, "food", seed_food_payload),
        (exercises, "exercise", seed_exercise_payload),
    ):
        payload["catalog_release"] = "zh-CN.2026-10-17.1"
        payload[f"{kind}s"][0]["name"] = "Localized"
        seed(database, payload)
    assert food_catalog.get_visible_food("user-a", private_food.id) == private_food
    assert exercise_catalog.search("user-a", "Private exercise", limit=10) == (
        private_exercise,
    )
    assert meals.list_meals("user-a", "2026-08-15") == old_meals
    assert workouts.list_sessions("user-a", "2026-08-15") == old_workouts
    assert _rows(database, "catalog_favorites") == old_favorites
    assert _rows(database, "catalog_usage") == old_usage
    assert _private_state(database, private_food.id, private_exercise.id) == private_state
    assert old_meals[0].items[0].food_name == "Original"
    assert old_workouts[0].strength_exercises[0].exercise_name == "Original"


def _private_state(database, food_id, exercise_id):
    with database.connection() as connection:
        state = {}
        for table in ("food_catalog", "exercise_catalog"):
            state[table] = tuple(
                tuple(row) for row in connection.execute(
                    f"SELECT * FROM {table} WHERE owner_user_id IS NOT NULL"
                    " ORDER BY rowid"
                )
            )
        state["aliases"] = tuple(
            tuple(row) for row in connection.execute(
                "SELECT * FROM catalog_aliases WHERE food_id = ? OR exercise_id = ?"
                " ORDER BY rowid", (food_id, exercise_id),
            )
        )
        state["search"] = tuple(
            tuple(row) for row in connection.execute(
                "SELECT * FROM catalog_search WHERE catalog_id IN (?, ?)"
                " ORDER BY rowid", (food_id, exercise_id),
            )
        )
        return state
