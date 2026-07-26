from __future__ import annotations

from backend.application.ports.daily_summary_repository import (
    DailySummary,
    DailySummaryRepository,
)


class DailySummaryService:
    def __init__(self, repository: DailySummaryRepository) -> None:
        self.repository = repository

    def get_day(
        self,
        user_id: str,
        log_date: str,
        timezone_name: str,
    ) -> DailySummary:
        return self.repository.get_day(user_id, log_date, timezone_name)

    def set_planned_meal_count(
        self,
        user_id: str,
        log_date: str,
        planned_meal_count: int,
        timezone_name: str,
    ) -> DailySummary:
        return self.repository.set_planned_meal_count(
            user_id,
            log_date,
            planned_meal_count,
            timezone_name,
        )
