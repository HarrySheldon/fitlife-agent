"""API routes for the Progress dashboard (KPIs, body trends, exercise PRs/1RM, execution)."""
from __future__ import annotations

from datetime import date as date_type, timedelta

from fastapi import APIRouter, Depends, Query

from backend.api.dependencies import require_current_user
from backend.api.preference_context import preferences_for
from backend.api.utils import ok
from backend.domain.account_clock import local_today
from backend.domain.body_measurements import compute_body_summary
from backend.infrastructure.repositories.cutover_fitness_repository import get_fitness_repository
from backend.infrastructure.repositories.sqlite_body_measurement_repository import (
    SQLiteBodyMeasurementRepository,
)
from backend.infrastructure.repositories.sqlite_exercise_progress_repository import (
    SQLiteExerciseProgressRepository,
)
from backend.infrastructure.repositories.sqlite_training_context_repository import (
    SQLiteTrainingContextRepository,
)
from backend.infrastructure.sqlite.runtime import get_database
from backend.schemas import AuthenticatedUser
from backend.tools.meal_analyzer import analyze_meals
from backend.tools.workout_analyzer import analyze_workouts

router = APIRouter(prefix="/api/v1/progress")


@router.get("/exercises")
def exercise_progress(
    days: int = Query(default=90, ge=7, le=3650),
    user: AuthenticatedUser = Depends(require_current_user),
):
    prefs = preferences_for(user)
    today = local_today(prefs.timezone).isoformat()
    repo = SQLiteExerciseProgressRepository(get_database())
    items = repo.list_progress(user.user_id, days=days, end_date=today)
    return ok(
        {
            "range_days": days,
            "exercises": [item.to_dict() for item in items],
        },
        processing_mode="deterministic",
    )


@router.get("/overview")
def progress_overview(
    days: int = Query(default=30, ge=7, le=3650),
    user: AuthenticatedUser = Depends(require_current_user),
):
    prefs = preferences_for(user)
    today_date = local_today(prefs.timezone)
    today_str = today_date.isoformat()
    db = get_database()

    fitness_repo = get_fitness_repository()
    profile = fitness_repo.read_profile(user.user_id)
    meals = fitness_repo.read_meals(user.user_id)
    workouts = fitness_repo.read_workouts(user.user_id)

    calorie_target = float(profile.daily_calorie_target or 0)
    protein_target = float(profile.daily_protein_target or 0)
    target_weight = float(profile.target_weight_kg) if profile.target_weight_kg else None

    meal_result = analyze_meals(meals, calorie_target, protein_target)
    workout_result = analyze_workouts(workouts)
    daily_meals = meal_result["daily_totals"]

    body_repo = SQLiteBodyMeasurementRepository(db)
    measurements = body_repo.list_for_user(user.user_id, days=days, end_date=today_str)
    body_summary = compute_body_summary(measurements, target_weight_kg=target_weight)

    exercise_repo = SQLiteExerciseProgressRepository(db)
    exercises = exercise_repo.list_progress(user.user_id, days=max(days, 90), end_date=today_str)

    training_ctx = SQLiteTrainingContextRepository(db).get(user.user_id)

    # Last 7 days adherence & nutrition hit counts
    last7_dates = {(today_date - timedelta(days=offset)).isoformat() for offset in range(7)}
    calorie_hit_days = 0
    protein_hit_days = 0
    logged_meal_days = 0
    for day_key in last7_dates:
        row = daily_meals.get(day_key)
        if not row:
            continue
        logged_meal_days += 1
        cals = float(row.get("calories", 0) or 0)
        prot = float(row.get("protein", 0) or 0)
        if calorie_target > 0 and (calorie_target * 0.85 <= cals <= calorie_target * 1.10):
            calorie_hit_days += 1
        if protein_target > 0 and prot >= protein_target * 0.90:
            protein_hit_days += 1

    # Workout adherence over last 7 days (M3 will override with active plan_cycle adherence when present)
    weekly_target_sessions = (
        training_ctx.weekly_available_days
        if training_ctx.configured
        else int(profile.weekly_training_frequency or 3)
    )
    recent_workout_days = _count_workout_days(workouts, last7_dates)
    adherence_mode = "weekly_frequency"
    adherence_completed = recent_workout_days
    adherence_planned = max(weekly_target_sessions, 1)
    adherence_pct = min(100, round(adherence_completed * 100 / adherence_planned))

    # Optional M3 hook: if an active plan cycle exists, compute adherence from scheduled plan_days
    cycle_adherence = _active_cycle_adherence_if_available(db, user.user_id, today_str)
    if cycle_adherence is not None:
        adherence_mode = "plan_cycle"
        adherence_completed = cycle_adherence["completed"]
        adherence_planned = cycle_adherence["planned"]
        adherence_pct = cycle_adherence["pct"]

    cutoff_str = (today_date - timedelta(days=days - 1)).isoformat()
    filtered_daily = {d: row for d, row in sorted(daily_meals.items()) if d >= cutoff_str}
    macro_totals = {"protein": 0.0, "carbs": 0.0, "fat": 0.0}
    for row in filtered_daily.values():
        for key in macro_totals:
            macro_totals[key] += float(row.get(key, 0) or 0)

    return ok(
        {
            "range_days": days,
            "today": today_str,
            "kpis": {
                "latest_weight_kg": body_summary.latest_weight_kg,
                "latest_7d_avg_kg": body_summary.latest_7d_avg_kg,
                "start_weight_kg": body_summary.start_weight_kg,
                "target_weight_kg": body_summary.target_weight_kg,
                "total_change_kg": body_summary.total_change_kg,
                "weekly_rate_kg": body_summary.weekly_rate_kg,
                "distance_to_target_kg": body_summary.distance_to_target_kg,
                "adherence_mode": adherence_mode,
                "adherence_completed": adherence_completed,
                "adherence_planned": adherence_planned,
                "adherence_pct": adherence_pct,
                "calorie_hit_days_7d": calorie_hit_days,
                "protein_hit_days_7d": protein_hit_days,
                "logged_meal_days_7d": logged_meal_days,
                "daily_calorie_target": round(calorie_target, 1),
                "daily_protein_target": round(protein_target, 1),
            },
            "body_summary": body_summary.to_dict(),
            "exercises": [item.to_dict() for item in exercises],
            "calorie_trend": [{"date": d, "value": round(float(row["calories"]), 1)} for d, row in filtered_daily.items()],
            "protein_trend": [{"date": d, "value": round(float(row["protein"]), 1)} for d, row in filtered_daily.items()],
            "workout_count_trend": [
                {"week": week, "value": count}
                for week, count in workout_result["weekly_training_counts"].items()
            ],
            "macro_distribution": [
                {"name": key, "value": round(val, 2)} for key, val in macro_totals.items()
            ],
            "training_context": training_ctx.to_dict(),
        },
        processing_mode="deterministic",
    )


def _count_workout_days(workouts, date_set: set[str]) -> int:
    if workouts.empty or "date" not in workouts:
        return 0
    matched: set[str] = set()
    for raw in workouts["date"].astype(str):
        try:
            iso = date_type.fromisoformat(raw[:10]).isoformat()
        except ValueError:
            continue
        if iso in date_set:
            matched.add(iso)
    return len(matched)


def _active_cycle_adherence_if_available(db, user_id: str, today_str: str) -> dict[str, int] | None:
    try:
        from backend.infrastructure.repositories.sqlite_plan_cycle_repository import (
            SQLitePlanCycleRepository,
        )
    except ImportError:
        return None
    repo = SQLitePlanCycleRepository(db)
    summary = repo.week_adherence_summary(user_id, today_str)
    if summary is None or summary["planned"] <= 0:
        return None
    return summary
