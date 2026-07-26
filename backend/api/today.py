from dataclasses import asdict
from datetime import date as calendar_date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from backend.api.dependencies import optional_current_user, require_current_user
from backend.api.preference_context import preferences_for
from backend.api.utils import ok
from backend.application.use_cases.daily_summary import DailySummaryService
from backend.domain.account_clock import local_today
from backend.infrastructure.repositories.sqlite_daily_summary_repository import (
    SQLiteDailySummaryRepository,
)
from backend.infrastructure.sqlite.runtime import get_database
from backend.schemas import AuthenticatedUser
from backend.tools.today_overview import build_today_overview


router = APIRouter()


class DailyLogUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planned_meal_count: int = Field(ge=1, le=12)


def get_daily_summary_service() -> DailySummaryService:
    return DailySummaryService(SQLiteDailySummaryRepository(get_database()))


@router.get("/today")
def today(
    date: calendar_date | None = None,
    user: AuthenticatedUser | None = Depends(optional_current_user),
    service: DailySummaryService = Depends(get_daily_summary_service),
):
    preferences = preferences_for(user)
    selected = date or local_today(preferences.timezone)
    day = selected.isoformat()
    if user is None:
        overview = build_today_overview(day)
        return ok(
            overview.model_dump(),
            processing_mode="deterministic",
        )
    summary = service.get_day(user.user_id, day, preferences.timezone)
    data = asdict(summary)
    if not summary.meals:
        data.pop("meals")
    if not summary.workouts:
        data.pop("workouts")
    data["coach_actions"] = [
        "explain_today",
        "suggest_next_meal",
    ]
    return ok(data, processing_mode="deterministic")


@router.patch("/api/v1/daily-logs/{log_date}")
def update_daily_log(
    log_date: calendar_date,
    payload: DailyLogUpdateRequest,
    user: AuthenticatedUser = Depends(require_current_user),
    service: DailySummaryService = Depends(get_daily_summary_service),
):
    timezone_name = preferences_for(user).timezone
    summary = service.set_planned_meal_count(
        user.user_id,
        log_date.isoformat(),
        payload.planned_meal_count,
        timezone_name,
    )
    return ok(asdict(summary), processing_mode="deterministic")
