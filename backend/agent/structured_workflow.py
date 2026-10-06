"""Runtime-backed structured suggestions; deterministic callers own all writes."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel

from backend.agent.contracts import AgentCommand, AgentOperation, AgentResult
from backend.agent.model_payloads import serialized_payload
from backend.agent.safety import SAFETY_RULE_VERSION, SafetyRefusal, check_input, review_output
from backend.agent.workflow import verify_guard_steps
from backend.application.ports.structured_model_gateway import StructuredModelGateway, StructuredModelResult
from backend.infrastructure.agent_runtime import factory
from backend.safety.context import sanitize_context
from backend.safety.gate import default_pack


@dataclass(frozen=True)
class StructuredAgentResult(StructuredModelResult):
    run_id: str
    request_id: str


@dataclass
class StructuredSuggestionWorkflow:
    instructions: str
    input_text: str
    response_model: type[BaseModel]
    gateway_resolver: Callable[[], StructuredModelGateway]
    # Set by the context guard; the writer sends this rather than the raw text.
    guarded_input_text: str = field(default="")

    async def execute(self, command, context) -> AgentResult:
        # The three guards run as named steps so verify_guard_steps can see them. They
        # used to be absent here: this workflow handed `input_text` - which carries
        # the user's own adjustment instructions and raw entry text - straight to the
        # model with no context check at all.
        await context.step("input_guard", lambda: check_input(command.question))
        await context.step("context_guard", lambda: self._guard_context(context))
        gateway = await context.step("model_configuration", self.gateway_resolver)
        context.set_model_metadata(provider=getattr(gateway, "provider", None), model=gateway.model)

        async def generate():
            return await context.tool("structured_suggestion_model", "safe", lambda: gateway.parse_structured(
                instructions=self.instructions, input_text=self.guarded_input_text,
                response_model=self.response_model,
            ))

        result = await context.step("writer", generate)
        context.set_model_metadata(provider=getattr(gateway, "provider", None), model=result.model)
        output = self.response_model.model_validate(result.output)
        serialized = output.model_dump_json()
        context.consume_output(serialized)

        def review():
            try:
                _, decision = review_output(command.question, serialized)
            except SafetyRefusal as refusal:
                # A prose fallback cannot safely replace a typed nutrition/plan
                # object, so a refusal stays a refusal.
                context.record("SAFETY_DECIDED", context, {
                    "outcome": refusal.decision.outcome,
                    "risk_category": refusal.decision.risk_category,
                    "rule_version": SAFETY_RULE_VERSION,
                })
                raise
            context.record("SAFETY_DECIDED", context, {
                "outcome": decision.outcome, "risk_category": decision.risk_category,
                "rule_version": SAFETY_RULE_VERSION,
            })
            if decision.outcome != "allow":
                raise SafetyRefusal(decision, command.question)
            return output

        reviewed = await context.step("safety_reviewer", review)
        verify_guard_steps(self, tuple(context.completed_steps))
        return await context.step("result_projector", lambda: AgentResult(
            answer_markdown="", intent=command.operation, trace={},
            tool_results={"structured": StructuredModelResult(reviewed, result.model, result.usage)},
            sources=(), model=result.model,
        ))

    def _guard_context(self, context) -> None:
        """Sanitise the free text this workflow is about to hand the model.

        The input gate has already looked at the question. This is the second, and
        different, check: the text below is what the user wrote earlier, and data can
        contain something that reads like an instruction.

        It runs as a named step so `verify_guard_steps` can see that it happened -
        this workflow previously had no context check at all, and nothing noticed.
        """
        payload = {"instructions": self.instructions, "input_text": self.input_text}
        sanitized, report = sanitize_context(payload, default_pack())
        self.guarded_input_text = sanitized["input_text"]
        context.consume_context(serialized_payload(sanitized))
        if not report.clean:
            context.record("SAFETY_DECIDED", context, {
                "outcome": "rewrite",
                "risk_category": "low",
                "rule_version": SAFETY_RULE_VERSION,
            })


def run_structured_agent(
    *, operation: AgentOperation, question: str, user_id: str | None,
    instructions: str, input_text: str, response_model: type[BaseModel],
    gateway_resolver: Callable[[], StructuredModelGateway], request_id: str | None = None,
    runtime=None,
) -> StructuredAgentResult:
    command = AgentCommand(operation=operation, question=question, user_id=user_id, request_id=request_id)
    outcome = (runtime or factory.get_agent_runtime()).execute_sync(command, StructuredSuggestionWorkflow(
        instructions, input_text, response_model, gateway_resolver,
    ))
    result = outcome.result.tool_results["structured"]
    return StructuredAgentResult(result.output, result.model, result.usage, outcome.run_id, outcome.request_id)
