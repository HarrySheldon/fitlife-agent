"""Thin compatibility entry points for the explicit FitLife runtime."""
from __future__ import annotations

from datetime import date as date_type
from dataclasses import replace
import json

from backend.agent.contracts import AgentCommand, AgentOperation
from backend.config import get_settings
from backend.infrastructure.agent_runtime.factory import CurrentAgentRuntime
from backend.agent.workflow import FitLifeWorkflow
from backend.application.ports.fitness_repository import FitnessRepository
from backend.application.ports.model_gateway import ModelGateway
from backend.application.use_cases.generate_plan import GeneratePlan
from backend.application.use_cases.generate_weekly_report import GenerateWeeklyReport
from backend.domain.errors import ApplicationError, ai_not_configured_error, model_gateway_error
from backend.domain.user_preferences import UserPreferences
from backend.infrastructure.model_gateway.factory import resolve_user_model_gateway
from backend.infrastructure.model_gateway.openai_responses import build_model_gateway
from backend.infrastructure.repositories.cutover_fitness_repository import get_fitness_repository
from backend.tools.target_suggestions import suggest_targets
from backend.tools.today_overview import build_today_overview_from_records

DEFAULT_AGENT_RUNTIME = CurrentAgentRuntime()


def run_fitlife_agent(
    question: str,
    user_id: str | None = None,
    *,
    repository: FitnessRepository | None = None,
    gateway: ModelGateway | None = None,
    initial_tool_results: dict | None = None,
    initial_tool_calls: list[str] | None = None,
    preferences: UserPreferences | None = None,
    operation: AgentOperation = "chat",
    surface: str | None = None,
    context_date: str | None = None,
    request_id: str | None = None,
) -> dict:
    command = AgentCommand(
        operation=operation,
        question=question,
        user_id=user_id,
        surface=surface,
        context_date=context_date,
        initial_tool_results=dict(initial_tool_results or {}),
        initial_tool_calls=tuple(initial_tool_calls or ()),
        request_id=request_id,
    )
    workflow = _LazyFitLifeWorkflow(repository, gateway, user_id, preferences or UserPreferences())
    return DEFAULT_AGENT_RUNTIME.execute_sync(command, workflow).to_dict()


def _review_mode() -> str:
    """Read the review mode once per run, from configuration rather than the request.

    A user cannot turn the review off by asking, and the value does not change midway
    through a run.
    """
    return get_settings().safety_review_mode


def _grounding_mode() -> str:
    """Read once per run, from configuration rather than from the request."""
    return get_settings().safety_grounding_mode


class _LazyFitLifeWorkflow:
    def __init__(self, repository, gateway, user_id, preferences, context_loader=None,
                 structured_gateway=None):
        self.repository, self.gateway, self.user_id, self.preferences = repository, gateway, user_id, preferences
        self.context_loader = context_loader
        self.structured_gateway = structured_gateway

    async def execute(self, command, context):
        repository = self.repository or await context.call(get_fitness_repository)
        if self.context_loader is not None:
            results, calls = await context.step("context_loader", lambda: self.context_loader(repository))
            context.consume_context(json.dumps(results, ensure_ascii=False, default=str))
            command = replace(command, initial_tool_results=results, initial_tool_calls=tuple(calls))
        gateway = self.gateway or await context.call(lambda: _resolve_gateway(self.user_id))
        workflow = FitLifeWorkflow(
            repository,
            gateway,
            context_metadata=self.preferences.model_dump(),
            review_mode=_review_mode(),
            structured_gateway=self.structured_gateway,
            grounding_mode=_grounding_mode(),
        )
        return await workflow.execute(command, context)


def run_contextual_coach_action(
    surface: str, action: str, date: str | None, question: str | None = None,
    user_id: str | None = None, *, repository: FitnessRepository | None = None,
    gateway: ModelGateway | None = None, preferences: UserPreferences | None = None,
    request_id: str | None = None,
) -> dict:
    command = AgentCommand(
        operation="coach_action", question=_coach_prompt(surface, action, date, question),
        user_id=user_id, surface=surface, context_date=date, request_id=request_id,
    )
    workflow = _LazyFitLifeWorkflow(
        repository, gateway, user_id, preferences or UserPreferences(),
        context_loader=lambda loaded_repository: _build_contextual_tool_context(action, date, user_id, loaded_repository),
    )
    result = DEFAULT_AGENT_RUNTIME.execute_sync(command, workflow).to_dict()
    result["trace"] = {**result.get("trace", {}), "surface": surface, "coach_action": action, "context_date": date}
    return result


def interpret_persisted_weekly_report(
    *, week: str, report: dict, user_id: str, repository: FitnessRepository | None = None,
    gateway: ModelGateway | None = None, preferences: UserPreferences | None = None,
    request_id: str | None = None,
) -> dict:
    result = run_fitlife_agent(
        f"Interpret the persisted deterministic weekly report for ISO week {week}. Use the supplied weekly_report as the report of record; do not generate or substitute another week.",
        user_id, repository=repository, gateway=gateway,
        initial_tool_results={"report_week": week, "weekly_report": report},
        initial_tool_calls=["load_persisted_weekly_report"], preferences=preferences,
        operation="weekly_review", surface="review",
        request_id=request_id,
    )
    result["trace"] = {**result.get("trace", {}), "surface": "review", "report_week": week}
    return result


def interpret_persisted_plan(
    *, plan_id: str, plan: dict, user_id: str, repository: FitnessRepository | None = None,
    gateway: ModelGateway | None = None, preferences: UserPreferences | None = None,
    request_id: str | None = None,
) -> dict:
    result = run_fitlife_agent(
        f"Review the persisted active fitness plan {plan_id} and recommend safe, useful adjustments. Use the supplied active_plan as the plan of record; do not generate, substitute, activate, or persist another plan.",
        user_id, repository=repository, gateway=gateway,
        initial_tool_results={"active_plan_id": plan_id, "active_plan": plan},
        initial_tool_calls=["load_persisted_plan"], preferences=preferences,
        operation="plan_review", surface="plan",
        request_id=request_id,
    )
    result["trace"] = {**result.get("trace", {}), "surface": "plan", "active_plan_id": plan_id}
    return result


def _resolve_gateway(user_id: str | None) -> ModelGateway:
    try:
        gateway = resolve_user_model_gateway(user_id) if user_id else build_model_gateway()
    except ApplicationError:
        raise
    except Exception as error:
        raise model_gateway_error(error) from None
    if gateway is None:
        raise ai_not_configured_error()
    return gateway


def _build_contextual_tool_context(
    action: str, date: str | None, user_id: str | None, repository: FitnessRepository,
) -> tuple[dict, list[str]]:
    if action == "suggest_targets":
        return {"target_suggestion": suggest_targets(repository.read_profile(user_id)).model_dump()}, ["suggest_targets"]
    if action == "explain_weekly_report":
        report = GenerateWeeklyReport(repository).execute(user_id)
        return {"weekly_report": report}, list(report["trace"]["tool_calls"])
    if action == "adjust_next_plan":
        plan = GeneratePlan(repository).execute(user_id)
        return {"generated_plan": plan}, list(plan["trace"]["tool_calls"])
    day = date or date_type.today().isoformat()
    overview = build_today_overview_from_records(day, repository.read_profile(user_id), repository.read_meals(user_id), repository.read_workouts(user_id))
    return {"today_overview": overview.model_dump()}, ["build_today_overview"]


def _coach_prompt(surface: str, action: str, date: str | None, question: str | None) -> str:
    base = {
        "explain_today": "Explain today's calorie, protein, and training status using the user's records.",
        "suggest_next_meal": "Suggest the next meal using today's remaining calorie and protein gap.",
        "adjust_today_training": "Suggest a practical training adjustment for today based on the user's profile and records.",
        "explain_weekly_report": "Create a weekly summary report, then explain the most important behavior change.",
        "adjust_next_plan": "Create a plan for next week and adjust it using recent records and the user's profile.",
        "suggest_targets": "Suggest calorie and protein targets from the user's body state, goal, and training frequency.",
    }[action]
    suffix = f" Date: {date}." if date else ""
    user_text = f" User question: {question}" if question else ""
    return f"{base} Surface: {surface}.{suffix}{user_text}"
