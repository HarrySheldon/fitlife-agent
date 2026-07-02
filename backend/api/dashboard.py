from fastapi import APIRouter

from backend.api.utils import ok
from backend.tools.data_access import read_meals, read_profile, read_workouts
from backend.tools.meal_analyzer import analyze_meals
from backend.tools.workout_analyzer import analyze_workouts


router = APIRouter(prefix="/dashboard")


@router.get("/summary")
def dashboard_summary():
    profile = read_profile()
    meals = read_meals()
    workouts = read_workouts()
    meal_result = analyze_meals(meals, profile.daily_calorie_target, profile.daily_protein_target)
    workout_result = analyze_workouts(workouts)
    daily = meal_result["daily_totals"]
    latest_day = sorted(daily)[-1] if daily else None
    latest = daily.get(latest_day, {}) if latest_day else {}
    macro_totals = {"protein": 0, "carbs": 0, "fat": 0}
    for row in daily.values():
        for key in macro_totals:
            macro_totals[key] += row.get(key, 0)

    data = {
        "today_calories": latest.get("calories", 0),
        "today_protein": latest.get("protein", 0),
        "weekly_training_count": sum(workout_result["weekly_training_counts"].values()),
        "weekly_training_duration_min": sum(workout_result["weekly_duration_min"].values()),
        "calorie_trend": [{"date": date, "value": row["calories"]} for date, row in daily.items()],
        "protein_trend": [{"date": date, "value": row["protein"]} for date, row in daily.items()],
        "workout_count_trend": [
            {"week": week, "value": count} for week, count in workout_result["weekly_training_counts"].items()
        ],
        "macro_distribution": [{"name": key, "value": round(value, 2)} for key, value in macro_totals.items()],
        "meal_summary": meal_result["summary"],
        "workout_summary": workout_result["summary"],
    }
    return ok(data)
