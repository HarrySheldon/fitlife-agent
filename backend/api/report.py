from fastapi import APIRouter, Depends

from backend.application.use_cases.generate_weekly_report import GenerateWeeklyReport
from backend.api.dependencies import optional_current_user
from backend.api.utils import ok
from backend.infrastructure.repositories.file_fitness_repository import FileFitnessRepository
from backend.schemas import AuthenticatedUser


router = APIRouter(prefix="/report")


@router.post("/weekly")
def weekly_report(user: AuthenticatedUser | None = Depends(optional_current_user)):
    user_id = user.user_id if user else None
    report = GenerateWeeklyReport(FileFitnessRepository()).execute(user_id)
    return ok(report, processing_mode="deterministic")
