from fastapi import APIRouter, Depends

from backend.agent.graph import interpret_persisted_weekly_report
from backend.application.use_cases.reports import WeeklyReports
from backend.application.use_cases.generate_weekly_report import GenerateWeeklyReport
from backend.api.dependencies import optional_current_user, require_current_user
from backend.api.preference_context import preferences_for
from backend.api.utils import ok
from backend.config import get_settings
from backend.domain.account_clock import local_week_bounds
from backend.infrastructure.repositories.cutover_fitness_repository import get_fitness_repository
from backend.infrastructure.repositories.file_report_repository import FileReportRepository
from backend.infrastructure.user_lifecycle import user_lifecycle_guard
from backend.schemas import AuthenticatedUser, CoachActionResponse


router = APIRouter(prefix="/report")


def _reports() -> WeeklyReports:
    generator = GenerateWeeklyReport(get_fitness_repository())
    return WeeklyReports(
        FileReportRepository(get_settings().data_dir),
        lambda user_id, start, end: generator.execute(user_id, start=start, end=end),
    )


@router.get("/weekly")
def list_weekly_reports(user: AuthenticatedUser = Depends(require_current_user)):
    reports = [item.model_dump(mode="json") for item in _reports().list(user.user_id)]
    return ok(reports, processing_mode="deterministic")


@router.get("/weekly/{week}")
def get_weekly_report(week: str, user: AuthenticatedUser = Depends(require_current_user)):
    report = _reports().get(user.user_id, week)
    return ok(report.model_dump(mode="json"), processing_mode="deterministic")


@router.post("/weekly/{week}/generate")
def generate_weekly_report(week: str, user: AuthenticatedUser = Depends(require_current_user)):
    report = _reports().generate(user.user_id, week)
    return ok(report.model_dump(mode="json"), processing_mode="deterministic")


@router.post("/weekly/{week}/interpret")
def interpret_weekly_report(week: str, user: AuthenticatedUser = Depends(require_current_user)):
    with user_lifecycle_guard(get_settings().data_dir, user.user_id):
        stored = _reports().get(user.user_id, week)
        result = interpret_persisted_weekly_report(
            week=week,
            report=stored.report.model_dump(),
            user_id=user.user_id,
            preferences=preferences_for(user),
        )
        response = CoachActionResponse(
            surface="review",
            action="explain_weekly_report",
            answer_markdown=result["answer_markdown"],
            intent=result["intent"],
            trace=result["trace"],
            sources=result.get("sources", []),
            model=result["model"],
            request_id=result["request_id"],
        )
        return ok(response.model_dump(), processing_mode="agent")


@router.post("/weekly")
def weekly_report(user: AuthenticatedUser | None = Depends(optional_current_user)):
    user_id = user.user_id if user else None
    start, end = local_week_bounds(preferences_for(user).timezone)
    report = GenerateWeeklyReport(get_fitness_repository()).execute(user_id, start=start, end=end)
    return ok(report, processing_mode="deterministic")
