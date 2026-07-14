from __future__ import annotations

from datetime import date

import pandas as pd

from backend.application.ports.fitness_repository import FitnessRepository
from backend.tools.meal_analyzer import analyze_meals
from backend.tools.report_generator import generate_weekly_report
from backend.tools.workout_analyzer import analyze_workouts


class GenerateWeeklyReport:
    def __init__(self, repository: FitnessRepository) -> None:
        self.repository = repository

    def execute(
        self,
        user_id: str | None = None,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> dict:
        profile = self.repository.read_profile(user_id)
        meals = _records_in_period(self.repository.read_meals(user_id), start, end)
        workouts = _records_in_period(self.repository.read_workouts(user_id), start, end)
        meal_result = analyze_meals(
            meals,
            profile.daily_calorie_target,
            profile.daily_protein_target,
        )
        workout_result = analyze_workouts(workouts)
        report = generate_weekly_report(profile.model_dump(), meal_result, workout_result)
        if start is not None and end is not None:
            report["period"] = {"start": start.isoformat(), "end": end.isoformat()}
        report["trace"] = {
            "tool_calls": [
                "load_profile",
                "analyze_meals",
                "analyze_workouts",
                "generate_weekly_report",
            ]
        }
        return report


def _records_in_period(frame: pd.DataFrame, start: date | None, end: date | None) -> pd.DataFrame:
    if start is None or end is None or frame.empty or "date" not in frame:
        return frame
    values = pd.to_datetime(frame["date"], errors="coerce").dt.date
    return frame[(values >= start) & (values <= end)]
