from fastapi import APIRouter, Depends

from backend.api.dependencies import optional_current_user
from backend.api.preference_context import preferences_for
from backend.api.utils import ok
from backend.domain.account_clock import local_today
from backend.schemas import AuthenticatedUser
from backend.tools.today_overview import build_today_overview


router = APIRouter()


@router.get("/today")
def today(date: str | None = None, user: AuthenticatedUser | None = Depends(optional_current_user)):
    day = date or local_today(preferences_for(user).timezone).isoformat()
    overview = build_today_overview(day, user.user_id if user else None)
    return ok(overview.model_dump(), processing_mode="deterministic")
