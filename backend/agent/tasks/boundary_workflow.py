"""Fixed product-boundary responses with the same mandatory safety seams.

The three sentences are product copy, not model output, so they are looked up in the
answer-language catalog. They were Chinese literals here before, which meant an English
account was refused in Chinese.
"""
from backend.agent.contracts import AgentResult
from backend.agent.safety import check_input, review_output
from backend.agent.workflow import verify_guard_steps
from backend.domain.coach_answer import AnswerLanguage, message_catalog
from backend.safety.context import sanitize_context
from backend.safety.gate import default_pack


class BoundaryWorkflow:
    def __init__(self, decision, *, language: AnswerLanguage) -> None:
        self.decision = decision
        self.language = language

    async def execute(self, command, context):
        catalog = message_catalog(self.language)
        await context.step("input_guard", lambda: check_input(command.question))
        await context.step("context_guard", lambda: sanitize_context({}, default_pack()))
        answer = (catalog.greeting
                  if self.decision.scope == "in_scope" else
                  catalog.clarification
                  if self.decision.needs_clarification else
                  catalog.out_of_scope)
        answer, _ = await context.step("safety_reviewer", lambda: review_output(command.question, answer, boundary_language=self.language))
        verify_guard_steps(self, tuple(context.completed_steps))
        return AgentResult(answer, "business_scope", {
            "scope": self.decision.scope, "refusal_code": self.decision.refusal_code,
            "needs_clarification": self.decision.needs_clarification,
            "tool_calls": [], "llm_used": False, "llm_answer_used": False,
            "answer_language": self.language,
        }, {}, (), "")
