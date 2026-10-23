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
from backend.application.ports.model_call_context import current_abort
from backend.application.ports.model_gateway import ModelGateway
from backend.application.ports.structured_model_gateway import StructuredModelGateway
from backend.application.use_cases.generate_plan import GeneratePlan
from backend.application.use_cases.generate_weekly_report import GenerateWeeklyReport
from backend.domain.errors import ApplicationError, ai_not_configured_error, model_gateway_error
from backend.domain.coach_answer import resolve_language
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
    _trusted_page_intent: bool = False,
    language: str | None = None,
    answer_mode: str | None = None,
    history_loader=None,
    coach_action: str | None = None,
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
        trusted_page_intent=_trusted_page_intent,
        language=language,
        answer_mode=answer_mode,
        coach_action=coach_action,
    )
    workflow = _LazyFitLifeWorkflow(repository, gateway, user_id, preferences or UserPreferences(), history_loader=history_loader)
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
                 structured_gateway=None, history_loader=None):
        self.repository, self.gateway, self.user_id, self.preferences = repository, gateway, user_id, preferences
        self.context_loader = context_loader
        self.structured_gateway = structured_gateway
        self.history_loader = history_loader

    async def execute(self, command, context):
        from backend.safety.business_scope import decide_business_scope, is_auxiliary_request
        from backend.agent.tasks.boundary_workflow import BoundaryWorkflow

        # Evaluate actual user text before repository, contextual tools or gateway.
        text = command.raw_coach_question if command.raw_coach_question is not None else command.question
        unified = get_settings().coach_agent_mode == 'unified' and command.operation in {'chat', 'coach_action'}
        if unified and not command.user_id:
            raise ApplicationError(code='AUTHENTICATION_REQUIRED', message='Sign in to use the unified coach.', status_code=401)
        scope = decide_business_scope(text)
        if not unified and (scope.scope == "out_of_scope" or scope.needs_clarification or is_auxiliary_request(text)):
            return await BoundaryWorkflow(
                scope,
                language=resolve_language(
                    requested=command.language,
                    account=self.preferences.language if self.preferences is not None else None,
                ),
            ).execute(command, context)
        if not unified and scope.scope == "mixed":
            command = replace(command, question="；".join(scope.allowed_subtasks))
        elif not unified and command.raw_coach_question and scope.scope == "unclear":
            # The generated page prompt cannot turn unrelated free text into a
            # fitness request. Let the planner see that original text alone.
            command = replace(command, question=command.raw_coach_question)
        if self.history_loader is not None:
            from backend.safety.context import sanitize_context
            from backend.safety.gate import default_pack
            from backend.agent.tasks.input_contracts import validate_context_findings, HistoryMessage
            remaining = max(0, context.policy.budget.max_tokens - context.tokens - context.output_tokens)
            # Keep most of the remaining budget for current facts, output and safety.
            projection = await context.call(lambda: self.history_loader(min(4000, remaining // 4)))
            history, report = sanitize_context(
                [dict(HistoryMessage(role=item.role, body=item.body).model_dump(), admitted_scope=item.admitted_scope) for item in projection.messages],
                default_pack(), scan_all=True,
            )
            validate_context_findings(report)
            context.consume_context(json.dumps(history, ensure_ascii=False))
            command = replace(command, recent_history=tuple(history))
        repository = self.repository or await context.call(get_fitness_repository)
        if not unified and self.context_loader is not None and not (command.raw_coach_question and scope.scope == "unclear"):
            results, calls = await context.step("context_loader", lambda: self.context_loader(repository))
            context.consume_context(json.dumps(results, ensure_ascii=False, default=str))
            command = replace(command, initial_tool_results=results, initial_tool_calls=tuple(calls))
        gateway = self.gateway or await context.call(lambda: _resolve_gateway(self.user_id))
        _register_abort(gateway)
        if unified:
            from backend.agent.coach_composition import build_unified_workflow
            command = replace(command, language=resolve_language(requested=command.language,
                account=self.preferences.language if self.preferences is not None else None))
            return await build_unified_workflow(command, repository, gateway).execute(command, context)
        structured_gateway = self.structured_gateway
        if structured_gateway is None and isinstance(gateway, StructuredModelGateway):
            structured_gateway = gateway
        workflow = FitLifeWorkflow(
            repository,
            gateway,
            context_metadata=self.preferences.model_dump(),
            review_mode=_review_mode(),
            structured_gateway=structured_gateway,
            grounding_mode=_grounding_mode(),
            # An explicit request for this turn beats the account setting, which beats
            # the app default. The question text is never consulted.
            answer_language=resolve_language(
                requested=command.language,
                account=self.preferences.language if self.preferences is not None else None,
            ),
            answer_mode=command.answer_mode,
            coach_action=command.coach_action,
        )
        return await workflow.execute(command, context)


def run_contextual_coach_action(
    surface: str, action: str, date: str | None, question: str | None = None,
    user_id: str | None = None, *, repository: FitnessRepository | None = None,
    gateway: ModelGateway | None = None, preferences: UserPreferences | None = None,
    request_id: str | None = None, language: str | None = None,
    answer_mode: str | None = None,
    history_loader=None,
    followup_detail: bool = False,
) -> dict:
    command = AgentCommand(
        operation="coach_action", question=_coach_prompt(surface, action, date, question)
            + (" Explain the reasons and provide more detail about this result." if followup_detail else ""),
        user_id=user_id, surface=surface, context_date=date, request_id=request_id,
        raw_coach_question=question or "",
        trusted_page_intent=not bool(question),
        language=language,
        answer_mode=answer_mode,
        coach_action=action,
    )
    workflow = _LazyFitLifeWorkflow(
        repository, gateway, user_id, preferences or UserPreferences(),
        context_loader=lambda loaded_repository: _build_contextual_tool_context(action, date, user_id, loaded_repository),
        history_loader=history_loader,
    )
    result = DEFAULT_AGENT_RUNTIME.execute_sync(command, workflow).to_dict()
    result["trace"] = {
        **result.get("trace", {}),
        "surface": surface,
        "coach_action": action,
        "context_date": date,
        # Auditable, so a reviewer can see which language rule applied without
        # re-reading the prompt.
        "answer_language": resolve_language(
            requested=language,
            account=(preferences or UserPreferences()).language,
        ),
        "answer_mode": answer_mode or "brief",
    }
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
        _trusted_page_intent=True,
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
        _trusted_page_intent=True,
        request_id=request_id,
    )
    result["trace"] = {**result.get("trace", {}), "surface": "plan", "active_plan_id": plan_id}
    return result


def _register_abort(gateway) -> None:
    """Let a cancel close this run's HTTP transport instead of orphaning it.

    The gateway owns a private ``httpx.Client``, so closing it here cannot affect
    another account's in-flight request.
    """
    abort = current_abort.get()
    close = getattr(gateway, "close", None)
    if abort is not None and callable(close):
        abort.register(close)


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
        # Explanation only. Generating an adjustment draft belongs to the plan task
        # service, which owns scope permission, the shared repair rounds and the atomic
        # confirmation. A Coach answer must not look like one of those drafts.
        "adjust_next_plan": "Explain the deterministic next-week plan draft using recent records and the user's profile. Do not create, change, activate or save a plan.",
        "suggest_targets": "Explain the deterministic calorie and protein target suggestion from the user's body state, goal and training frequency. Do not propose different targets.",
    }[action]
    suffix = f" Date: {date}." if date else ""
    user_text = f" User question: {question}" if question else ""
    return f"{base} Surface: {surface}.{suffix}{user_text}"
