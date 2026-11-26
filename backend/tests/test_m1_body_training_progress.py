"""M1 backend tests: body measurements time-series, training context, and exercise PR/1RM progress."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.domain.body_measurements import BodyMeasurement, compute_body_summary
from backend.domain.exercise_progress import StrengthSetRow, aggregate_exercise_progress, estimate_epley_1rm
from backend.domain.training_context import InjuryLimitation
from backend.infrastructure.repositories.postgres_body_measurement_repository import (
    PostgresBodyMeasurementRepository,
)
from backend.infrastructure.repositories.postgres_exercise_progress_repository import (
    PostgresExerciseProgressRepository,
)
from backend.infrastructure.repositories.postgres_training_context_repository import (
    PostgresTrainingContextRepository,
)


def _db(pg_db):
    return pg_db


def test_body_summary_computes_7d_moving_average_and_weekly_rate():
    rows = [
        BodyMeasurement(id="1", user_id="u1", measured_date="2026-10-01", measured_at="2026-10-01T08:00:00Z", weight_kg=74.0, waist_cm=84.0),
        BodyMeasurement(id="2", user_id="u1", measured_date="2026-10-03", measured_at="2026-10-03T08:00:00Z", weight_kg=73.4),
        BodyMeasurement(id="3", user_id="u1", measured_date="2026-10-05", measured_at="2026-10-05T08:00:00Z", weight_kg=73.1),
        BodyMeasurement(id="4", user_id="u1", measured_date="2026-10-05", measured_at="2026-10-05T20:00:00Z", weight_kg=73.2, body_fat_pct=19.5),
        BodyMeasurement(id="5", user_id="u1", measured_date="2026-10-15", measured_at="2026-10-15T08:00:00Z", weight_kg=72.0, waist_cm=82.5),
    ]
    summary = compute_body_summary(rows, target_weight_kg=68.0)

    assert summary.count == 5
    assert summary.weight_count == 4
    assert summary.start_weight_kg == 74.0
    assert summary.latest_weight_kg == 72.0
    assert summary.total_change_kg == -2.0
    # 2 kg lost over 14 days = -1.0 kg/week
    assert summary.weekly_rate_kg == -1.0
    assert summary.distance_to_target_kg == 4.0
    assert summary.latest_body_fat_pct == 19.5
    assert summary.latest_waist_cm == 82.5
    # On 2026-10-05, 7-day window includes 10-01 (74.0), 10-03 (73.4), 10-05 (73.2 latest) -> avg 73.53
    oct5 = next(p for p in summary.trend if p.date == "2026-10-05")
    assert oct5.weight_kg == 73.2
    assert oct5.moving_avg_7d == pytest.approx(73.53, abs=0.01)


def test_body_measurement_repository_crud_and_owner_isolation(pg_db):
    db = _db(pg_db)
    repo = PostgresBodyMeasurementRepository(db)

    m1 = repo.create("user-a", measured_date="2026-11-01", weight_kg=72.5, body_fat_pct=18.2, note="morning")
    repo.create("user-b", measured_date="2026-11-01", weight_kg=60.0)

    a_rows = repo.list_for_user("user-a", days=30, end_date="2026-11-10")
    assert len(a_rows) == 1
    assert a_rows[0].id == m1.id
    assert a_rows[0].weight_kg == 72.5

    # Cannot delete another owner's measurement
    assert repo.delete("user-b", m1.id) is False
    assert repo.delete("user-a", m1.id) is True
    assert repo.latest_for_user("user-a") is None


def test_training_context_repository_defaults_and_upsert(pg_db):
    db = _db(pg_db)
    repo = PostgresTrainingContextRepository(db)

    default_ctx = repo.get("user-a")
    assert default_ctx.configured is False
    assert default_ctx.weekly_available_days == 3

    saved = repo.upsert(
        "user-a",
        available_equipment=["barbell", "dumbbell", "barbell"],
        weekly_available_days=4,
        session_duration_min=60,
        experience_level="intermediate",
        preferred_split="upper_lower",
        injury_or_limitations=[InjuryLimitation(area="knee", note="avoid deep jump squats")],
        notes="Prefer morning sessions",
    )
    assert saved.configured is True
    assert saved.available_equipment == ("barbell", "dumbbell")
    assert saved.weekly_available_days == 4
    assert saved.injury_or_limitations[0].area == "knee"

    reloaded = repo.get("user-a")
    assert reloaded.to_dict() == saved.to_dict()


def test_epley_1rm_and_exercise_progress_aggregation(pg_db):
    assert estimate_epley_1rm(100.0, 1) == 100.0
    assert estimate_epley_1rm(100.0, 6) == 120.0
    assert estimate_epley_1rm(60.0, 15) is None
    assert estimate_epley_1rm(None, 10) is None

    db = _db(pg_db)
    with db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO training_sessions (id, user_id, log_date, title, duration_min, intensity, entry_method)
            VALUES
                ('s1', 'u1', '2026-10-01', 'Leg Day 1', 50, 'medium', 'form'),
                ('s2', 'u1', '2026-10-08', 'Leg Day 2', 55, 'high', 'form')
            """
        )
        conn.execute(
            """
            INSERT INTO strength_exercises (id, session_id, catalog_exercise_id, exercise_name, primary_muscle, position)
            VALUES
                ('se1', 's1', NULL, 'Barbell Squat', 'legs', 1),
                ('se2', 's2', NULL, 'Barbell Squat', 'legs', 1)
            """
        )
        conn.execute(
            """
            INSERT INTO strength_sets (id, strength_exercise_id, set_number, reps, load_kg, bodyweight)
            VALUES
                ('set1', 'se1', 1, 8, 60.0, 0),
                ('set2', 'se1', 2, 8, 60.0, 0),
                ('set3', 'se2', 1, 8, 67.5, 0),
                ('set4', 'se2', 2, 6, 70.0, 0)
            """
        )

    repo = PostgresExerciseProgressRepository(db)
    progress = repo.list_progress("u1", days=90, end_date="2026-10-15")
    assert len(progress) == 1
    squat = progress[0]
    assert squat.exercise_name == "Barbell Squat"
    assert squat.session_count == 2
    assert squat.best_weight_kg == 70.0
    # s1 best 1RM: 60*(1+8/30)=76.0; s2 best 1RM: max(67.5*(1+8/30)=85.5, 70*(1+6/30)=84.0) = 85.5
    assert squat.best_1rm_kg == 85.5
    assert squat.delta_1rm_kg == pytest.approx(9.5, abs=0.01)
    assert len(squat.series) == 2


def test_aggregate_exercise_progress_pure_function():
    rows = [
        StrengthSetRow("2026-10-01", "s1", "ex-bench", "Bench Press", "chest", 5, 80.0, False),
        StrengthSetRow("2026-10-05", "s2", "ex-bench", "Bench Press", "chest", 5, 85.0, False),
    ]
    res = aggregate_exercise_progress(rows)
    assert len(res) == 1
    assert res[0].best_weight_kg == 85.0
    assert res[0].delta_1rm_kg == pytest.approx(5.84, abs=0.02)
