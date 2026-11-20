"""M3 backend tests: periodized plan cycles, catalog selection, adherence, and workout draft prefill."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from backend.application.ports.workout_repository import (
    CustomExerciseSnapshot,
    StrengthExerciseInput,
    WorkoutDraftInput,
)
from backend.application.use_cases.workouts import WorkoutService
from backend.domain.exercise_progress import ExerciseProgressSummary
from backend.domain.plan_cycles import (
    CatalogExerciseOption,
    build_personalized_cycle_draft,
    compute_day_adherence,
)
from backend.domain.training_context import InjuryLimitation, TrainingContext
from backend.domain.workouts import StrengthSet
from backend.infrastructure.repositories.sqlite_plan_cycle_repository import (
    SQLitePlanCycleRepository,
)
from backend.infrastructure.repositories.sqlite_workout_repository import (
    SQLiteWorkoutRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


def _db(tmp_path: Path) -> SQLiteDatabase:
    db = SQLiteDatabase(tmp_path / "m3.sqlite3")
    run_migrations(db, RECORDS_MIGRATIONS)
    return db


def _sample_catalog() -> tuple[CatalogExerciseOption, ...]:
    return (
        CatalogExerciseOption("ex-squat", "杠铃深蹲", "strength", "股四头肌", "barbell", "compound", "intermediate"),
        CatalogExerciseOption("ex-bench", "哑铃卧推", "strength", "胸肌", "dumbbell", "compound", "beginner"),
        CatalogExerciseOption("ex-row", "哑铃划船", "strength", "中背部肌群", "dumbbell", "compound", "beginner"),
        CatalogExerciseOption("ex-rdl", "哑铃罗马尼亚硬拉", "strength", "腘绳肌", "dumbbell", "compound", "intermediate"),
        CatalogExerciseOption("ex-plank", "平板支撑", "strength", "腹肌", "body only", "static", "beginner"),
        CatalogExerciseOption("ex-run", "慢跑", "cardio", "cardiovascular", "body only", "", "beginner"),
    )


def test_personalized_cycle_respects_equipment_days_rest_and_progressive_overload():
    ctx = TrainingContext(
        user_id="u1",
        available_equipment=("dumbbell", "bodyweight"),
        weekly_available_days=7,  # Must cap at 6 training days + 1 mandatory rest day
        session_duration_min=45,
        experience_level="intermediate",
        preferred_split="auto",
        injury_or_limitations=(InjuryLimitation(area="knee", note="no jump squats"),),
        configured=True,
    )
    progress = (
        ExerciseProgressSummary(
            exercise_key="ex-bench",
            catalog_exercise_id="ex-bench",
            exercise_name="哑铃卧推",
            primary_muscle="胸肌",
            session_count=4,
            latest_date="2026-11-15",
            best_weight_kg=25.0,
            best_1rm_kg=31.0,
            best_volume_kg=900.0,
            latest_weight_kg=25.0,
            latest_1rm_kg=31.0,
            delta_1rm_kg=3.0,
            series=(),
        ),
    )

    cycle_payload, days = build_personalized_cycle_draft(
        user_id="u1",
        goal_type="fat_loss",
        start_date=date(2026, 11, 18),  # Wednesday -> Monday 2026-11-16
        duration_weeks=8,
        training_context=ctx,
        catalog=_sample_catalog(),
        exercise_progress=progress,
        recent_adherence_pct=90,
    )

    assert cycle_payload["start_date"] == "2026-11-16"
    assert cycle_payload["duration_weeks"] == 8
    assert len(days) == 56
    week1 = [d for d in days if d["week_index"] == 1]
    assert sum(1 for d in week1 if d["day_type"] == "rest") >= 1
    assert any("至少保留 1 天休息日" in w for w in cycle_payload["rationale"]["warnings"])

    # Week 1 bench should pick dumbbell bench and suggest progressive overload (+2.5kg -> 27.5kg)
    bench_entries = [
        ex
        for d in week1
        for ex in d["prescribed_exercises"]
        if ex["catalog_exercise_id"] == "ex-bench"
    ]
    assert bench_entries
    assert bench_entries[0]["target_weight_kg"] == 27.5


def test_plan_cycle_lifecycle_adherence_and_atomic_activation(tmp_path: Path):
    db = _db(tmp_path)
    repo = SQLitePlanCycleRepository(db)
    ctx = TrainingContext(user_id="u1", weekly_available_days=3, configured=True)

    c1_payload, c1_days = build_personalized_cycle_draft(
        user_id="u1",
        goal_type="muscle_gain",
        start_date=date(2026, 11, 16),
        duration_weeks=2,
        training_context=ctx,
        catalog=_sample_catalog(),
    )
    draft1 = repo.create_draft("u1", c1_payload, c1_days)
    assert draft1.status == "draft"
    assert repo.get_active_cycle("u1") is None

    # Activate draft1 explicitly
    active1 = repo.activate_cycle("u1", draft1.id)
    assert active1 is not None and active1.status == "active"
    assert repo.discard_draft("u1", draft1.id) is False  # Active cycle cannot be discarded as draft

    # Log a workout on Monday (first training day: 2026-11-16)
    with db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO training_sessions (id, user_id, log_date, title, duration_min, intensity, entry_method)
            VALUES ('ts-1', 'u1', '2026-11-16', 'Full Body A', 45, 'medium', 'form')
            """
        )

    # Check Wednesday (2026-11-18) adherence: Mon completed, Wed upcoming, Fri upcoming -> 1/3 = 33%
    adherence = repo.week_adherence_summary("u1", "2026-11-18")
    assert adherence is not None
    assert adherence["completed"] == 1
    assert adherence["planned"] == 3
    assert adherence["pct"] == 33

    # Skip Wednesday's day -> planned drops to 2, completed 1 -> 50%
    match = repo.get_active_day_for_date("u1", "2026-11-18")
    assert match is not None
    _, wed_day = match
    repo.update_day("u1", wed_day.id, status_override="skipped")
    adherence_after_skip = repo.week_adherence_summary("u1", "2026-11-18")
    assert adherence_after_skip is not None
    assert adherence_after_skip["skipped"] == 1
    assert adherence_after_skip["planned"] == 2
    assert adherence_after_skip["pct"] == 50

    # Create draft2 and activate -> draft1 atomically becomes archived
    draft2 = repo.create_draft("u1", c1_payload, c1_days)
    active2 = repo.activate_cycle("u1", draft2.id)
    assert active2 is not None and active2.status == "active"
    old1 = repo.get_cycle("u1", draft1.id)
    assert old1 is not None and old1.status == "archived"


def test_prefill_workout_creates_unconfirmed_draft_not_formal_session(tmp_path: Path):
    db = _db(tmp_path)
    with db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO user_profile_versions (
                id, user_id, age, height_cm, weight_kg, energy_parameter,
                activity_level, effective_from
            )
            VALUES ('p1', 'u1', 30, 175, 70.0, 'male', 'moderate', '2026-01-01T00:00:00Z')
            """
        )
    workout_service = WorkoutService(SQLiteWorkoutRepository(db))
    draft = workout_service.create_draft(
        "u1",
        WorkoutDraftInput(
            log_date="2026-11-16",
            title="下肢力量",
            started_at=None,
            duration_min=50.0,
            intensity="medium",
            entry_method="form",
            strength_exercises=(
                StrengthExerciseInput(
                    sets=(StrengthSet(set_number=1, reps=8, load_kg=60.0, bodyweight=False),),
                    custom_exercise=CustomExerciseSnapshot(
                        name="深蹲",
                        exercise_type="strength",
                        primary_muscle="股四头肌",
                        secondary_muscles=(),
                        met=None,
                    ),
                ),
            ),
            cardio_items=(),
        ),
    )
    assert draft.id
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM training_sessions WHERE user_id = 'u1'").fetchone()[0] == 0
