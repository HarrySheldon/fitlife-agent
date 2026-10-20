"""Adapts the existing agent entry points to the narrow answer port.

The turn service does not know how an answer is produced; this module does, and
nothing else. It also deliberately does not catch anything: a safety refusal or a
model failure must reach the service so the turn ends in the right state instead
of being published as a partial answer.
"""

from __future__ import annotations

from backend.agent.graph import run_contextual_coach_action, run_fitlife_agent
from backend.application.ports.coach_answer import CoachTurnAnswer, CoachTurnRequest
from backend.application.use_cases.coach_conversations import CoachConversations
from backend.config import get_settings
from backend.domain.errors import ApplicationError
from backend.infrastructure.repositories.file_plan_repository import FilePlanRepository
from backend.infrastructure.repositories.file_report_repository import FileReportRepository
from backend.safety.business_scope import is_closed_followup

CHAT_ACTION = "chat"


class RuntimeCoachAnswerAdapter:
    def __init__(self, *, contextual=None, chat=None, conversations=None, plans=None, reports=None) -> None:
        self.contextual = contextual or run_contextual_coach_action
        self.chat = chat or run_fitlife_agent
        self.conversations, self.plans, self.reports = conversations, plans, reports

    def run(self, request: CoachTurnRequest) -> CoachTurnAnswer:
        history_options = {}
        if self.conversations is not None:
            history_options["history_loader"] = lambda budget: CoachConversations(self.conversations).context(
                request.user_id, conversation_id=request.conversation_id,
                turn_id=request.turn_id, character_budget=budget,
            )
        if request.plan_id or request.report_week:
            if request.plan_id:
                stored = (self.plans or FilePlanRepository(get_settings().data_dir)).get(request.user_id, request.plan_id)
                if stored is None:
                    raise ApplicationError(code="PLAN_NOT_FOUND", message="The saved plan was not found.", status_code=404)
                facts = {"active_plan_id": request.plan_id, "active_plan": stored.plan.model_dump(mode="json")}
                question = "Explain the supplied saved fitness plan. Do not generate, change, activate or save any plan."
                operation, tool = "plan_review", "load_persisted_plan"
            else:
                stored = (self.reports or FileReportRepository(get_settings().data_dir)).get(request.user_id, request.report_week)
                if stored is None:
                    raise ApplicationError(code="REPORT_NOT_FOUND", message="The saved report was not found.", status_code=404)
                facts = {"report_week": request.report_week, "weekly_report": stored.report.model_dump(mode="json")}
                question = "Explain the supplied saved fitness weekly report. Do not generate or substitute another report."
                operation, tool = "weekly_review", "load_persisted_weekly_report"
            if is_closed_followup(request.question):
                question += " Explain the reasons and provide more detail about this result."
            result = self.chat(question, request.user_id, initial_tool_results=facts,
                initial_tool_calls=[tool], operation=operation, surface=request.surface,
                _trusted_page_intent=True, preferences=request.preferences,
                coach_action=request.action,
                language=request.language, answer_mode=request.answer_mode,
                request_id=request.request_id, **history_options)
        elif request.action == CHAT_ACTION:
            result = self.chat(
                request.question,
                request.user_id,
                preferences=request.preferences,
                request_id=request.request_id,
                language=request.language,
                answer_mode=request.answer_mode,
                **history_options,
            )
        else:
            if is_closed_followup(request.question):
                history_options["followup_detail"] = True
            result = self.contextual(
                surface=request.surface,
                action=request.action,
                date=request.date,
                # For a registered shortcut this is the human-readable message
                # stored in the transcript, not an extra free-text instruction.
                # Free questions use the separate chat branch above. Passing the
                # label here would disable trusted context loading as "unclear".
                question=None,
                user_id=request.user_id,
                preferences=request.preferences,
                request_id=request.request_id,
                language=request.language,
                answer_mode=request.answer_mode,
                **history_options,
            )
        return CoachTurnAnswer(
            answer_markdown=str(result["answer_markdown"]),
            model=str(result.get("model") or ""),
            sources=tuple(result.get("sources") or ()),
            trace=dict(result.get("trace") or {}),
        )
