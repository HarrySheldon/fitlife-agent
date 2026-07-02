from fastapi import APIRouter

from backend.api.utils import ok
from backend.tools.data_access import read_meals, read_profile, read_workouts
from backend.tools.meal_analyzer import analyze_meals
from backend.tools.report_generator import generate_weekly_report
from backend.tools.workout_analyzer import analyze_workouts


router = APIRouter(prefix="/report")


@router.post("/weekly")
def weekly_report():
    profile = read_profile()
    meal = analyze_meals(read_meals(), profile.daily_calorie_target, profile.daily_protein_target)
    workout = analyze_workouts(read_workouts())
    report = generate_weekly_report(profile.model_dump(), meal, workout)
    report["trace"] = {"tool_calls": ["load_profile", "analyze_meals", "analyze_workouts", "generate_weekly_report"]}
    return ok(report)
