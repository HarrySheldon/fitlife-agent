from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends

from backend.api.dependencies import optional_current_user
from backend.api.utils import ok
from backend.schemas import AgentEntryRequest, AuthenticatedUser, MealRecord, WorkoutRecord
from backend.tools.calendar_store import create_agent_entry, create_meal, create_workout, get_daily_detail, list_daily_summaries


router = APIRouter(prefix="/calendar")


@router.get("/days")
def days(
    start: str | None = None,
    end: str | None = None,
    user: AuthenticatedUser | None = Depends(optional_current_user),
):
    end = end or date.today().isoformat()
    start = start or (date.fromisoformat(end) - timedelta(days=29)).isoformat()
    summaries = list_daily_summaries(start, end, _user_id(user))
    return ok([summary.model_dump() for summary in summaries], processing_mode="deterministic")


@router.get("/day/{day}")
def day_detail(day: str, user: AuthenticatedUser | None = Depends(optional_current_user)):
    return ok(get_daily_detail(day, _user_id(user)).model_dump(), processing_mode="deterministic")


@router.post("/meals")
def add_meal(record: MealRecord, user: AuthenticatedUser | None = Depends(optional_current_user)):
    return ok(
        create_meal(record, _user_id(user)).model_dump(),
        "Meal saved",
        processing_mode="deterministic",
    )


@router.post("/workouts")
def add_workout(record: WorkoutRecord, user: AuthenticatedUser | None = Depends(optional_current_user)):
    return ok(
        create_workout(record, _user_id(user)).model_dump(),
        "Workout saved",
        processing_mode="deterministic",
    )


@router.post("/agent-entry")
def add_agent_entry(request: AgentEntryRequest, user: AuthenticatedUser | None = Depends(optional_current_user)):
    return ok(
        create_agent_entry(request, _user_id(user)).model_dump(),
        "Entry parsed",
        processing_mode="deterministic",
    )


def _user_id(user: AuthenticatedUser | None) -> str | None:
    return user.user_id if user else None
