from fastapi import APIRouter, Depends

from backend.application.use_cases.generate_weekly_report import GenerateWeeklyReport
from backend.api.dependencies import optional_current_user
from backend.api.preference_context import preferences_for
from backend.api.utils import ok
from backend.domain.account_clock import local_week_bounds
from backend.infrastructure.repositories.file_fitness_repository import FileFitnessRepository
from backend.schemas import AuthenticatedUser


router = APIRouter(prefix="/report")


@router.post("/weekly")
def weekly_report(user: AuthenticatedUser | None = Depends(optional_current_user)):
    user_id = user.user_id if user else None
    start, end = local_week_bounds(preferences_for(user).timezone)
    report = GenerateWeeklyReport(FileFitnessRepository()).execute(user_id, start=start, end=end)
    return ok(report, processing_mode="deterministic")
