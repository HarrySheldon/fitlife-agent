from datetime import date as date_type, timedelta

from fastapi import APIRouter, Depends

from backend.api.dependencies import optional_current_user
from backend.api.preference_context import preferences_for
from backend.api.utils import ok
from backend.domain.account_clock import local_today
from backend.schemas import AuthenticatedUser
from backend.tools.data_access import read_meals, read_profile, read_workouts
from backend.tools.meal_analyzer import analyze_meals
from backend.tools.workout_analyzer import analyze_workouts


router = APIRouter(prefix="/dashboard")


@router.get("/summary")
def dashboard_summary(date: str | None = None, user: AuthenticatedUser | None = Depends(optional_current_user)):
    user_id = user.user_id if user else None
    profile = read_profile(user_id)
    meals = read_meals(user_id)
    workouts = read_workouts(user_id)
    meal_result = analyze_meals(meals, profile.daily_calorie_target, profile.daily_protein_target)
    workout_result = analyze_workouts(workouts)
    daily = meal_result["daily_totals"]
    summary_date = date or local_today(preferences_for(user).timezone).isoformat()
    latest = daily.get(summary_date, {})
    weekly_workouts = _workouts_for_week(workouts, summary_date)
    macro_totals = {"protein": 0, "carbs": 0, "fat": 0}
    for row in daily.values():
        for key in macro_totals:
            macro_totals[key] += row.get(key, 0)

    data = {
        "summary_date": summary_date,
        "today_calories": latest.get("calories", 0),
        "today_protein": latest.get("protein", 0),
        "weekly_training_count": int(len(weekly_workouts)),
        "weekly_training_duration_min": float(weekly_workouts["duration_min"].sum()) if not weekly_workouts.empty else 0,
        "calorie_trend": [{"date": date, "value": row["calories"]} for date, row in daily.items()],
        "protein_trend": [{"date": date, "value": row["protein"]} for date, row in daily.items()],
        "workout_count_trend": [
            {"week": week, "value": count} for week, count in workout_result["weekly_training_counts"].items()
        ],
        "macro_distribution": [{"name": key, "value": round(value, 2)} for key, value in macro_totals.items()],
        "meal_summary": meal_result["summary"],
        "workout_summary": workout_result["summary"],
    }
    return ok(data, processing_mode="deterministic")


def _workouts_for_week(workouts, selected_date: str):
    if workouts.empty or "date" not in workouts:
        return workouts.iloc[0:0]
    current = date_type.fromisoformat(selected_date)
    start = current - timedelta(days=current.weekday())
    end = start + timedelta(days=6)
    dates = workouts["date"].astype(str).map(date_type.fromisoformat)
    return workouts[(dates >= start) & (dates <= end)]
