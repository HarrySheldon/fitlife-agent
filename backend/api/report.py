from fastapi import APIRouter, Depends

from backend.api.dependencies import optional_current_user
from backend.api.utils import ok
from backend.schemas import AuthenticatedUser
from backend.tools.data_access import read_meals, read_profile, read_workouts
from backend.tools.meal_analyzer import analyze_meals
from backend.tools.report_generator import generate_weekly_report
from backend.tools.workout_analyzer import analyze_workouts


router = APIRouter(prefix="/report")


@router.post("/weekly")
def weekly_report(user: AuthenticatedUser | None = Depends(optional_current_user)):
    user_id = user.user_id if user else None
    profile = read_profile(user_id)
    meal = analyze_meals(read_meals(user_id), profile.daily_calorie_target, profile.daily_protein_target)
    workout = analyze_workouts(read_workouts(user_id))
    report = generate_weekly_report(profile.model_dump(), meal, workout)
    report["trace"] = {"tool_calls": ["load_profile", "analyze_meals", "analyze_workouts", "generate_weekly_report"]}
    return ok(report)
