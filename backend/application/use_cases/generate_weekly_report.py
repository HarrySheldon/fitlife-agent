from __future__ import annotations

from backend.application.ports.fitness_repository import FitnessRepository
from backend.tools.meal_analyzer import analyze_meals
from backend.tools.report_generator import generate_weekly_report
from backend.tools.workout_analyzer import analyze_workouts


class GenerateWeeklyReport:
    def __init__(self, repository: FitnessRepository) -> None:
        self.repository = repository

    def execute(self, user_id: str | None = None) -> dict:
        profile = self.repository.read_profile(user_id)
        meal_result = analyze_meals(
            self.repository.read_meals(user_id),
            profile.daily_calorie_target,
            profile.daily_protein_target,
        )
        workout_result = analyze_workouts(self.repository.read_workouts(user_id))
        report = generate_weekly_report(profile.model_dump(), meal_result, workout_result)
        report["trace"] = {
            "tool_calls": [
                "load_profile",
                "analyze_meals",
                "analyze_workouts",
                "generate_weekly_report",
            ]
        }
        return report
