from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from backend.application.ports.workout_repository import (
    CardioItemInput,
    CustomExerciseSnapshot,
    StrengthExerciseInput,
    WorkoutDraftInput,
    WorkoutRepositoryError,
)
from backend.domain.workouts import StrengthSet
from backend.infrastructure.repositories.sqlite_workout_repository import (
    SQLiteWorkoutRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


NOW = datetime(2026, 7, 25, 12, tzinfo=timezone.utc)


def _database(tmp_path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "workouts.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
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
    return database


def _insert_exercise(
    database: SQLiteDatabase,
    exercise_id: str,
    *,
    name: str,
    exercise_type: str,
    primary_muscle: str,
    met: float | None = None,
    owner_user_id: str | None = None,
) -> None:
    source = "public" if owner_user_id is None else "user_custom"
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO exercise_catalog (
                id, owner_user_id, source, source_name, source_record_id,
                name, exercise_type, primary_muscle,
                secondary_muscles_json, met, provenance_json
            ) VALUES (?, ?, ?, 'test', ?, ?, ?, ?, '[]', ?, '{}')
            """,
            (
                exercise_id,
                owner_user_id,
                source,
                exercise_id,
                name,
                exercise_type,
                primary_muscle,
                met,
            ),
        )


def _mixed_payload() -> WorkoutDraftInput:
    return WorkoutDraftInput(
        log_date="2026-07-25",
        title="Mixed session",
        started_at=None,
        duration_min=45,
        intensity="medium",
        entry_method="form",
        strength_exercises=(
            StrengthExerciseInput(
                catalog_exercise_id="squat",
                sets=(
                    StrengthSet(1, 8, 60, False),
                    StrengthSet(2, 8, 60, False),
                    StrengthSet(3, 8, 60, False),
                ),
            ),
        ),
        cardio_items=(
            CardioItemInput(
                catalog_exercise_id="running",
                duration_min=20,
                device_calories=None,
            ),
        ),
    )


def test_draft_resolves_owned_snapshots_estimates_and_optimistic_versions(
    tmp_path,
):
    database = _database(tmp_path)
    _insert_exercise(
        database,
        "squat",
        name="Squat",
        exercise_type="strength",
        primary_muscle="quadriceps",
    )
    _insert_exercise(
        database,
        "running",
        name="Running",
        exercise_type="cardio",
        primary_muscle="cardiovascular",
        met=9.8,
    )
    repository = SQLiteWorkoutRepository(database, clock=lambda: NOW)

    draft = repository.create_draft(
        "user-a",
        _mixed_payload(),
        expires_at="2026-08-24T12:00:00Z",
    )

    assert draft.version == 1
    assert draft.payload.weight_kg_snapshot == 70
    assert draft.payload.strength_exercises[0].exercise_name == "Squat"
    assert len(draft.payload.strength_exercises[0].sets) == 3
    assert draft.payload.cardio_items[0].estimated_calories == 240.1
    assert draft.payload.cardio_items[0].is_estimate is True
    assert draft.payload.estimated_calories == 515.7
    updated = repository.update_draft(
        "user-a",
        draft.id,
        expected_version=1,
        payload=_mixed_payload(),
    )
    assert updated.version == 2
    with pytest.raises(WorkoutRepositoryError) as stale:
        repository.update_draft(
            "user-a",
            draft.id,
            expected_version=1,
            payload=_mixed_payload(),
        )
    assert stale.value.code == "DRAFT_VERSION_CONFLICT"


def test_confirm_atomically_persists_mixed_session_and_replays_key(tmp_path):
    database = _database(tmp_path)
    _insert_exercise(
        database,
        "squat",
        name="Squat",
        exercise_type="strength",
        primary_muscle="quadriceps",
    )
    _insert_exercise(
        database,
        "running",
        name="Running",
        exercise_type="cardio",
        primary_muscle="cardiovascular",
        met=9.8,
    )
    repository = SQLiteWorkoutRepository(database, clock=lambda: NOW)
    draft = repository.create_draft(
        "user-a",
        _mixed_payload(),
        expires_at="2026-08-24T12:00:00Z",
    )

    confirmed = repository.confirm(
        "user-a",
        draft.id,
        expected_version=1,
        idempotency_key="confirm-workout",
        request_fingerprint="same",
    )
    replay = repository.confirm(
        "user-a",
        draft.id,
        expected_version=1,
        idempotency_key="confirm-workout",
        request_fingerprint="same",
    )

    assert replay.id == confirmed.id
    assert replay.replayed is True
    assert len(confirmed.strength_exercises[0].sets) == 3
    assert confirmed.cardio_items[0].estimated_calories == 240.1
    assert repository.get_draft("user-a", draft.id) is None
    assert repository.list_sessions("user-a", "2026-07-25") == (confirmed,)
    with database.connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM strength_sets"
        ).fetchone()[0] == 3
        assert connection.execute(
            "SELECT COUNT(*) FROM catalog_usage WHERE user_id = 'user-a'"
        ).fetchone()[0] == 2


def test_custom_exercise_and_foreign_catalog_visibility(tmp_path):
    database = _database(tmp_path)
    _insert_exercise(
        database,
        "foreign",
        name="Foreign",
        exercise_type="strength",
        primary_muscle="back",
        owner_user_id="user-b",
    )
    repository = SQLiteWorkoutRepository(database, clock=lambda: NOW)
    foreign = WorkoutDraftInput(
        **{
            **_mixed_payload().__dict__,
            "strength_exercises": (
                StrengthExerciseInput(
                    catalog_exercise_id="foreign",
                    sets=(StrengthSet(1, 8, 20, False),),
                ),
            ),
            "cardio_items": (),
        }
    )
    with pytest.raises(WorkoutRepositoryError) as hidden:
        repository.create_draft(
            "user-a",
            foreign,
            expires_at="2026-08-24T12:00:00Z",
        )
    assert hidden.value.code == "EXERCISE_NOT_VISIBLE"

    custom = WorkoutDraftInput(
        **{
            **_mixed_payload().__dict__,
            "strength_exercises": (
                StrengthExerciseInput(
                    custom_exercise=CustomExerciseSnapshot(
                        name="My movement",
                        exercise_type="strength",
                        primary_muscle="glutes",
                        secondary_muscles=("hamstrings",),
                        met=None,
                    ),
                    sets=(StrengthSet(1, 10, None, True),),
                ),
            ),
            "cardio_items": (),
        }
    )
    draft = repository.create_draft(
        "user-a",
        custom,
        expires_at="2026-08-24T12:00:00Z",
    )
    confirmed = repository.confirm(
        "user-a",
        draft.id,
        expected_version=1,
        idempotency_key="custom",
        request_fingerprint="custom",
    )
    assert confirmed.strength_exercises[0].catalog_exercise_id is not None


def test_confirm_rolls_back_complete_graph_when_child_insert_fails(tmp_path):
    database = _database(tmp_path)
    _insert_exercise(
        database,
        "squat",
        name="Squat",
        exercise_type="strength",
        primary_muscle="quadriceps",
    )
    _insert_exercise(
        database,
        "running",
        name="Running",
        exercise_type="cardio",
        primary_muscle="cardiovascular",
        met=9.8,
    )
    repository = SQLiteWorkoutRepository(database, clock=lambda: NOW)
    draft = repository.create_draft(
        "user-a",
        _mixed_payload(),
        expires_at="2026-08-24T12:00:00Z",
    )
    with database.transaction() as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_strength_set
            BEFORE INSERT ON strength_sets
            BEGIN
                SELECT RAISE(ABORT, 'simulated failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError):
        repository.confirm(
            "user-a",
            draft.id,
            expected_version=1,
            idempotency_key="rollback",
            request_fingerprint="rollback",
        )

    assert repository.get_draft("user-a", draft.id) == draft
    with database.connection() as connection:
        for table in (
            "training_sessions",
            "strength_exercises",
            "strength_sets",
            "cardio_items",
            "catalog_usage",
            "idempotency_keys",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0] == 0


def test_owner_isolation_and_concurrent_retries_create_one_session(tmp_path):
    database = _database(tmp_path)
    _insert_exercise(
        database,
        "squat",
        name="Squat",
        exercise_type="strength",
        primary_muscle="quadriceps",
    )
    _insert_exercise(
        database,
        "running",
        name="Running",
        exercise_type="cardio",
        primary_muscle="cardiovascular",
        met=9.8,
    )
    setup = SQLiteWorkoutRepository(database, clock=lambda: NOW)
    draft = setup.create_draft(
        "user-a",
        _mixed_payload(),
        expires_at="2026-08-24T12:00:00Z",
    )
    assert setup.get_draft("user-b", draft.id) is None

    def confirm():
        return SQLiteWorkoutRepository(database, clock=lambda: NOW).confirm(
            "user-a",
            draft.id,
            expected_version=1,
            idempotency_key="concurrent",
            request_fingerprint="same",
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _index: confirm(), range(4)))

    assert {item.id for item in results} == {results[0].id}
    assert len(setup.list_sessions("user-a", "2026-07-25")) == 1
    assert setup.list_sessions("user-b", "2026-07-25") == ()
