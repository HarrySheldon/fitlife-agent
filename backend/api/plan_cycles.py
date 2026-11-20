"""API routes for periodized plan cycles, daily schedule adherence, and one-click workout prefill."""
from __future__ import annotations

from datetime import date as calendar_date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.api.dependencies import require_current_user
from backend.api.preference_context import preferences_for
from backend.api.utils import ok
from backend.application.ports.workout_repository import (
    CardioItemInput,
    CustomExerciseSnapshot,
    StrengthExerciseInput,
    WorkoutDraftInput,
)
from backend.application.use_cases.workouts import WorkoutService
from backend.domain.account_clock import local_today
from backend.domain.errors import ApplicationError
from backend.domain.plan_cycles import (
    GoalType,
    PrescribedExercise,
    build_personalized_cycle_draft,
    compute_day_adherence,
    monday_of_week,
)
from backend.domain.workouts import StrengthSet
from backend.infrastructure.repositories.cutover_fitness_repository import get_fitness_repository
from backend.infrastructure.repositories.sqlite_exercise_progress_repository import (
    SQLiteExerciseProgressRepository,
)
from backend.infrastructure.repositories.sqlite_plan_cycle_repository import (
    SQLitePlanCycleRepository,
)
from backend.infrastructure.repositories.sqlite_training_context_repository import (
    SQLiteTrainingContextRepository,
)
from backend.infrastructure.repositories.sqlite_workout_repository import (
    SQLiteWorkoutRepository,
)
from backend.infrastructure.sqlite.runtime import get_database
from backend.schemas import AuthenticatedUser

router = APIRouter(prefix="/api/v1/plan-cycles")


class CreatePlanCycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=120)
    goal_type: GoalType | None = None
    start_date: calendar_date | None = None
    duration_weeks: int = Field(default=8, ge=1, le=24)


class PrescribedExerciseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_exercise_id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    primary_muscle: str = Field(default="full_body", max_length=60)
    exercise_type: Literal["strength", "cardio"] = "strength"
    sets: int = Field(default=3, ge=1, le=12)
    reps: int = Field(default=10, ge=1, le=60)
    target_weight_kg: float | None = Field(default=None, ge=0, le=500)
    duration_min: int | None = Field(default=None, ge=5, le=240)
    rest_sec: int = Field(default=90, ge=15, le=300)
    notes: str = Field(default="", max_length=200)


class UpdatePlanDayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    focus: str | None = Field(default=None, max_length=120)
    day_type: Literal["training", "rest", "cardio"] | None = None
    status_override: Literal["skipped"] | None = None
    clear_status_override: bool = False
    prescribed_exercises: list[PrescribedExerciseInput] | None = None
    notes: str | None = Field(default=None, max_length=400)


def _repo() -> SQLitePlanCycleRepository:
    return SQLitePlanCycleRepository(get_database())


@router.get("")
def list_plan_cycles(user: AuthenticatedUser = Depends(require_current_user)):
    repo = _repo()
    cycles = repo.list_cycles(user.user_id)
    active = next((c.to_dict() for c in cycles if c.status == "active"), None)
    drafts = [c.to_dict() for c in cycles if c.status == "draft"]
    history = [c.to_dict() for c in cycles if c.status not in {"active", "draft"}]
    return ok({"active": active, "drafts": drafts, "history": history}, processing_mode="deterministic")


@router.get("/active")
def get_active_plan_cycle(
    date: calendar_date | None = Query(default=None),
    week_index: int | None = Query(default=None, ge=1, le=24),
    user: AuthenticatedUser = Depends(require_current_user),
):
    prefs = preferences_for(user)
    today_date = local_today(prefs.timezone)
    today_iso = today_date.isoformat()
    anchor = date or today_date
    repo = _repo()

    all_cycles = repo.list_cycles(user.user_id)
    active = next((c for c in all_cycles if c.status == "active"), None)
    drafts = [
        {
            **draft.to_dict(),
            "week1_days": [d.to_dict() for d in repo.get_cycle_days(user.user_id, draft.id, week_index=1)],
        }
        for draft in all_cycles
        if draft.status == "draft"
    ]

    if active is None:
        return ok(
            {
                "active": None,
                "current_week": None,
                "days": [],
                "adherence": None,
                "drafts": drafts,
                "history": [c.to_dict() for c in all_cycles if c.status not in {"active", "draft"}],
            },
            processing_mode="deterministic",
        )

    cycle_start = calendar_date.fromisoformat(active.start_date)
    computed_week = max(1, min(active.duration_weeks, ((anchor - cycle_start).days // 7) + 1))
    selected_week = min(active.duration_weeks, week_index) if week_index is not None else computed_week
    days = repo.get_cycle_days(user.user_id, active.id, week_index=selected_week)

    if days:
        logged = repo.logged_workout_counts_by_date(
            user.user_id, days[0].scheduled_date, days[-1].scheduled_date
        )
    else:
        logged = {}

    enriched_days = []
    planned = completed = missed = skipped = 0
    for day in days:
        status, count = compute_day_adherence(day, logged_workout_dates=logged, today_iso=today_iso)
        enriched_days.append(day.to_dict(adherence=status, logged_session_count=count))
        if status == "skipped":
            skipped += 1
        elif status != "rest":
            planned += 1
            if status == "completed":
                completed += 1
            elif status == "missed":
                missed += 1

    pct = min(100, round(completed * 100 / planned)) if planned > 0 else 100
    return ok(
        {
            "active": active.to_dict(),
            "current_week": selected_week,
            "days": enriched_days,
            "adherence": {
                "completed": completed,
                "planned": planned,
                "missed": missed,
                "skipped": skipped,
                "pct": pct,
            },
            "drafts": drafts,
            "history": [c.to_dict() for c in all_cycles if c.status not in {"active", "draft"}],
        },
        processing_mode="deterministic",
    )


@router.get("/today")
def get_today_plan(
    date: calendar_date | None = Query(default=None),
    user: AuthenticatedUser = Depends(require_current_user),
):
    prefs = preferences_for(user)
    today_date = local_today(prefs.timezone)
    target_date = (date or today_date).isoformat()
    repo = _repo()
    match = repo.get_active_day_for_date(user.user_id, target_date)
    if match is None:
        return ok({"cycle": None, "day": None}, processing_mode="deterministic")
    cycle, day = match
    logged = repo.logged_workout_counts_by_date(user.user_id, target_date, target_date)
    status, count = compute_day_adherence(
        day, logged_workout_dates=logged, today_iso=today_date.isoformat()
    )
    return ok(
        {
            "cycle": {
                "id": cycle.id,
                "title": cycle.title,
                "duration_weeks": cycle.duration_weeks,
                "goal_type": cycle.goal_type,
            },
            "day": day.to_dict(adherence=status, logged_session_count=count),
        },
        processing_mode="deterministic",
    )


@router.post("", status_code=201)
def create_plan_cycle_draft(
    payload: CreatePlanCycleRequest,
    user: AuthenticatedUser = Depends(require_current_user),
):
    db = get_database()
    prefs = preferences_for(user)
    today_date = local_today(prefs.timezone)
    repo = SQLitePlanCycleRepository(db)
    training_ctx = SQLiteTrainingContextRepository(db).get(user.user_id)
    exercises_progress = SQLiteExerciseProgressRepository(db).list_progress(
        user.user_id, days=90, end_date=today_date.isoformat()
    )
    adherence = repo.week_adherence_summary(user.user_id, (today_date - timedelta(days=7)).isoformat())
    goal = payload.goal_type or _goal_from_profile(user.user_id)
    catalog = repo.load_catalog_options(user.user_id)
    start = payload.start_date or monday_of_week(today_date)

    cycle_payload, days_payload = build_personalized_cycle_draft(
        user_id=user.user_id,
        goal_type=goal,
        start_date=start,
        duration_weeks=payload.duration_weeks,
        training_context=training_ctx,
        catalog=catalog,
        exercise_progress=exercises_progress,
        recent_adherence_pct=adherence["pct"] if adherence else None,
        title=payload.title,
        source="deterministic",
    )
    created = repo.create_draft(user.user_id, cycle_payload, days_payload)
    week1 = repo.get_cycle_days(user.user_id, created.id, week_index=1)
    return ok(
        {
            "cycle": created.to_dict(),
            "week1_days": [d.to_dict() for d in week1],
        },
        processing_mode="deterministic",
    )


@router.post("/{cycle_id}/activate")
def activate_plan_cycle(
    cycle_id: str,
    user: AuthenticatedUser = Depends(require_current_user),
):
    repo = _repo()
    activated = repo.activate_cycle(user.user_id, cycle_id)
    if activated is None:
        raise ApplicationError(
            code="PLAN_CYCLE_NOT_FOUND",
            message="Plan cycle was not found.",
            status_code=404,
        )
    return ok({"cycle": activated.to_dict()}, processing_mode="deterministic")


@router.delete("/{cycle_id}")
def discard_plan_cycle_draft(
    cycle_id: str,
    user: AuthenticatedUser = Depends(require_current_user),
):
    repo = _repo()
    deleted = repo.discard_draft(user.user_id, cycle_id)
    if not deleted:
        raise ApplicationError(
            code="PLAN_CYCLE_DRAFT_NOT_FOUND",
            message="Draft plan cycle was not found.",
            status_code=404,
        )
    return ok({"deleted": True, "cycle_id": cycle_id}, processing_mode="deterministic")


@router.patch("/days/{day_id}")
def update_plan_day(
    day_id: str,
    payload: UpdatePlanDayRequest,
    user: AuthenticatedUser = Depends(require_current_user),
):
    repo = _repo()
    status_override: object = ...
    if payload.clear_status_override:
        status_override = None
    elif payload.status_override is not None:
        status_override = payload.status_override

    exercises_dicts = (
        [PrescribedExercise.from_dict(item.model_dump()).to_dict() for item in payload.prescribed_exercises]
        if payload.prescribed_exercises is not None
        else None
    )
    updated = repo.update_day(
        user.user_id,
        day_id,
        focus=payload.focus,
        day_type=payload.day_type,
        status_override=status_override,
        prescribed_exercises=exercises_dicts,
        notes=payload.notes,
    )
    if updated is None:
        raise ApplicationError(
            code="PLAN_DAY_NOT_FOUND",
            message="Plan day was not found.",
            status_code=404,
        )
    return ok({"day": updated.to_dict()}, processing_mode="deterministic")


@router.post("/days/{day_id}/prefill-workout", status_code=201)
def prefill_workout_from_plan_day(
    day_id: str,
    user: AuthenticatedUser = Depends(require_current_user),
):
    """Create a standard unconfirmed WorkoutDraft prefilled from a scheduled PlanDay.

    Formal workout records still require explicit user review and confirmation in WorkoutEntry.
    """
    db = get_database()
    repo = SQLitePlanCycleRepository(db)
    day = repo.get_day(user.user_id, day_id)
    if day is None:
        raise ApplicationError(
            code="PLAN_DAY_NOT_FOUND",
            message="Plan day was not found.",
            status_code=404,
        )

    strength_inputs: list[StrengthExerciseInput] = []
    cardio_inputs: list[CardioItemInput] = []
    for ex in day.prescribed_exercises:
        if ex.exercise_type == "cardio":
            if ex.catalog_exercise_id:
                cardio_inputs.append(
                    CardioItemInput(
                        duration_min=float(ex.duration_min or day.estimated_duration_min or 30),
                        device_calories=None,
                        catalog_exercise_id=ex.catalog_exercise_id,
                    )
                )
            else:
                cardio_inputs.append(
                    CardioItemInput(
                        duration_min=float(ex.duration_min or day.estimated_duration_min or 30),
                        device_calories=None,
                        custom_exercise=CustomExerciseSnapshot(
                            name=ex.name,
                            exercise_type="cardio",
                            primary_muscle=ex.primary_muscle or "cardiovascular",
                            secondary_muscles=(),
                            met=6.0,
                        ),
                    )
                )
        else:
            sets = tuple(
                StrengthSet(
                    set_number=idx + 1,
                    reps=ex.reps,
                    load_kg=ex.target_weight_kg,
                    bodyweight=ex.target_weight_kg is None,
                )
                for idx in range(ex.sets)
            )
            if ex.catalog_exercise_id:
                strength_inputs.append(
                    StrengthExerciseInput(
                        sets=sets,
                        catalog_exercise_id=ex.catalog_exercise_id,
                    )
                )
            else:
                strength_inputs.append(
                    StrengthExerciseInput(
                        sets=sets,
                        custom_exercise=CustomExerciseSnapshot(
                            name=ex.name,
                            exercise_type="strength",
                            primary_muscle=ex.primary_muscle or "full_body",
                            secondary_muscles=(),
                            met=None,
                        ),
                    )
                )

    workout_service = WorkoutService(SQLiteWorkoutRepository(db))
    draft = workout_service.create_draft(
        user.user_id,
        WorkoutDraftInput(
            log_date=day.scheduled_date,
            title=day.focus or "按计划训练",
            started_at=None,
            duration_min=float(day.estimated_duration_min) if day.estimated_duration_min else None,
            intensity="medium",
            entry_method="form",
            strength_exercises=tuple(strength_inputs),
            cardio_items=tuple(cardio_inputs),
        ),
    )
    return ok(
        {
            "draft_id": draft.id,
            "log_date": day.scheduled_date,
            "day_id": day.id,
        },
        processing_mode="deterministic",
    )


def _goal_from_profile(user_id: str) -> GoalType:
    try:
        profile = get_fitness_repository().read_profile(user_id)
        if profile.goal in ("fat_loss", "muscle_gain", "maintenance"):
            return profile.goal  # type: ignore[return-value]
    except Exception:
        pass
    return "maintenance"
