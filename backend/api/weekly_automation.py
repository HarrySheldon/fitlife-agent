"""API routes for weekly lazy automation and on-demand personalized cycle draft generation."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from backend.api.dependencies import require_current_user
from backend.api.preference_context import preferences_for
from backend.api.utils import ok
from backend.application.use_cases.generate_weekly_report import GenerateWeeklyReport
from backend.application.use_cases.reports import WeeklyReports
from backend.application.use_cases.weekly_automation import WeeklyAutomationService, iso_week_id
from backend.config import get_settings
from backend.domain.account_clock import local_today
from backend.domain.plan_cycles import GoalType
from backend.api.profile_resolution import resolve_authoritative_profile_context
from backend.infrastructure.repositories.cutover_fitness_repository import get_fitness_repository
from backend.infrastructure.repositories.file_report_repository import FileReportRepository
from backend.infrastructure.repositories.sqlite_plan_cycle_repository import SQLitePlanCycleRepository
from backend.infrastructure.sqlite.runtime import get_database
from backend.schemas import AuthenticatedUser

router = APIRouter()


class DismissAutomationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    iso_week: str | None = Field(default=None, max_length=16)


class PersonalizedDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=120)
    goal_type: GoalType | None = None
    duration_weeks: int = Field(default=4, ge=1, le=24)
    focus_note: str = Field(default="", max_length=240)


def _profile_goal_and_target(user_id: str) -> tuple[GoalType, float | None]:
    try:
        profile = get_fitness_repository().read_profile(user_id)
        ctx = resolve_authoritative_profile_context(get_database(), user_id, profile)
        return ctx.goal, ctx.target_weight_kg
    except Exception:
        return "maintenance", None


def _ensure_report(user_id: str, week: str) -> str:
    repo = FileReportRepository(get_settings().data_dir)
    if repo.get(user_id, week) is not None:
        return "already_exists"
    generator = GenerateWeeklyReport(get_fitness_repository())
    reports = WeeklyReports(
        repo,
        lambda uid, start, end: generator.execute(uid, start=start, end=end),
    )
    reports.generate(user_id, week)
    return "generated"


@router.post("/api/v1/weekly-automation/check")
def check_weekly_automation(user: AuthenticatedUser = Depends(require_current_user)):
    prefs = preferences_for(user)
    today = local_today(prefs.timezone)
    goal, target_weight = _profile_goal_and_target(user.user_id)
    service = WeeklyAutomationService(get_database())
    run = service.check_and_run(
        user.user_id,
        today,
        goal_type=goal,
        target_weight_kg=target_weight,
        ensure_weekly_report=_ensure_report,
    )
    return ok({"run": run.to_dict()}, processing_mode="deterministic")


@router.get("/api/v1/weekly-automation/status")
def get_weekly_automation_status(user: AuthenticatedUser = Depends(require_current_user)):
    prefs = preferences_for(user)
    today = local_today(prefs.timezone)
    service = WeeklyAutomationService(get_database())
    run = service.get_run(user.user_id, iso_week_id(today))
    return ok({"run": run.to_dict() if run else None}, processing_mode="deterministic")


@router.post("/api/v1/weekly-automation/dismiss")
def dismiss_weekly_automation(
    payload: DismissAutomationRequest,
    user: AuthenticatedUser = Depends(require_current_user),
):
    prefs = preferences_for(user)
    today = local_today(prefs.timezone)
    target_week = payload.iso_week or iso_week_id(today)
    service = WeeklyAutomationService(get_database())
    dismissed = service.dismiss(user.user_id, target_week)
    return ok({"dismissed": dismissed, "iso_week": target_week}, processing_mode="deterministic")


@router.post("/api/v1/plan-cycles/generate-personalized", status_code=201)
def generate_personalized_plan_draft(
    payload: PersonalizedDraftRequest,
    user: AuthenticatedUser = Depends(require_current_user),
):
    prefs = preferences_for(user)
    today = local_today(prefs.timezone)
    default_goal, target_weight = _profile_goal_and_target(user.user_id)
    service = WeeklyAutomationService(get_database())
    created = service.generate_personalized_draft(
        user.user_id,
        today,
        duration_weeks=payload.duration_weeks,
        goal_type=payload.goal_type or default_goal,
        target_weight_kg=target_weight,
        focus_note=payload.focus_note,
        source="agent",
        title=payload.title,
    )
    week1 = SQLitePlanCycleRepository(get_database()).get_cycle_days(
        user.user_id, created.id, week_index=1
    )
    return ok(
        {
            "cycle": created.to_dict(),
            "week1_days": [d.to_dict() for d in week1],
        },
        processing_mode="deterministic",
    )
