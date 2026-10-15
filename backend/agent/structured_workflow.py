"""Runtime-backed structured suggestions; deterministic callers own all writes."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel, ValidationError

from backend.agent.contracts import AgentCommand, AgentOperation, AgentResult
from backend.agent.safety import SAFETY_RULE_VERSION, SafetyRefusal, check_input, review_output
from backend.agent.workflow import verify_guard_steps
from backend.agent.semantic_review import ObservationReviewer, ReviewMode, collect_review
from backend.config import get_settings
from backend.application.ports.structured_model_gateway import StructuredModelGateway, StructuredModelResult
from backend.infrastructure.agent_runtime import factory


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
    review_mode: ReviewMode = "off"

    async def execute(self, command, context) -> AgentResult:
        # The three guards run as named steps so verify_guard_steps can see them. They
        # used to be absent here: this workflow handed `input_text` - which carries
        # the user's own adjustment instructions and raw entry text - straight to the
        # model with no context check at all.
        await context.step("input_guard", lambda: check_input(command.question))
        await context.step("context_guard", lambda: self._guard_context(context, command))
        from backend.safety.business_scope import decide_business_scope
        from backend.agent.tasks.input_contracts import InputClarificationRequired
        scope = decide_business_scope(command.question)
        if scope.scope == "out_of_scope":
            await context.step("safety_reviewer", lambda: review_output(command.question, "Please provide a fitness or nutrition request."))
            verify_guard_steps(self, tuple(context.completed_steps))
            raise InputClarificationRequired("BUSINESS_SCOPE_NOT_SUPPORTED")
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

        async def review():
            try:
                _, decision = review_output(command.question, serialized)
                if decision.outcome != "allow":
                    raise SafetyRefusal(decision, command.question)
                observation = await collect_review(
                    context, gateway, self.review_mode, command.question, serialized,
                )
                context.record("SAFETY_REVIEWED", context, {
                    "review_mode": observation.mode, "review_status": observation.status,
                })
                if self.review_mode == "enforce":
                    _, decision = review_output(
                        command.question, serialized,
                        reviewer=ObservationReviewer(observation, self.review_mode),
                    )
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

    def _guard_context(self, context, command) -> None:
        """Sanitise the free text this workflow is about to hand the model.

        The input gate has already looked at the question. This is the second, and
        different, check: the text below is what the user wrote earlier, and data can
        contain something that reads like an instruction.

        It runs as a named step so `verify_guard_steps` can see that it happened -
        this workflow previously had no context check at all, and nothing noticed.
        """
        from backend.agent.tasks.input_contracts import structured_stage_input, InputClarificationRequired
        try:
            payload = structured_stage_input(command.operation, self.input_text)
        except ValidationError:
            # Only validation of this user supplied DTO is a user error. Gateway
            # output validation and programming faults retain their own handling.
            raise InputClarificationRequired() from None
        self.guarded_input_text = payload.model_dump_json()
        context.consume_context(self.instructions + self.guarded_input_text)


def run_structured_agent(
    *, operation: AgentOperation, question: str, user_id: str | None,
    instructions: str, input_text: str, response_model: type[BaseModel],
    gateway_resolver: Callable[[], StructuredModelGateway], request_id: str | None = None,
    runtime=None,
) -> StructuredAgentResult:
    command = AgentCommand(operation=operation, question=question, user_id=user_id, request_id=request_id)
    outcome = (runtime or factory.get_agent_runtime()).execute_sync(command, StructuredSuggestionWorkflow(
        instructions, input_text, response_model, gateway_resolver,
        review_mode=get_settings().safety_review_mode,
    ))
    result = outcome.result.tool_results["structured"]
    return StructuredAgentResult(result.output, result.model, result.usage, outcome.run_id, outcome.request_id)
