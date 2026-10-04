"""Runtime-backed structured suggestions; deterministic callers own all writes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel

from backend.agent.contracts import AgentCommand, AgentOperation, AgentResult
from backend.agent.safety import SAFETY_RULE_VERSION, SafetyRefusal, check_input, review_output
from backend.application.ports.structured_model_gateway import StructuredModelGateway, StructuredModelResult
from backend.infrastructure.agent_runtime import factory


@dataclass(frozen=True)
class StructuredAgentResult(StructuredModelResult):
    run_id: str
    request_id: str


@dataclass(frozen=True)
class StructuredSuggestionWorkflow:
    instructions: str
    input_text: str
    response_model: type[BaseModel]
    gateway_resolver: Callable[[], StructuredModelGateway]

    async def execute(self, command, context) -> AgentResult:
        # Also protects direct workflow callers; Runtime owns the input event.
        check_input(command.question)
        context.consume_context(self.instructions + self.input_text)
        gateway = await context.step("model_configuration", self.gateway_resolver)
        context.set_model_metadata(provider=getattr(gateway, "provider", None), model=gateway.model)

        async def generate():
            return await context.tool("structured_suggestion_model", "safe", lambda: gateway.parse_structured(
                instructions=self.instructions, input_text=self.input_text,
                response_model=self.response_model,
            ))

        result = await context.step("writer", generate)
        context.set_model_metadata(provider=getattr(gateway, "provider", None), model=result.model)
        output = self.response_model.model_validate(result.output)
        serialized = output.model_dump_json()
        context.consume_output(serialized)

        def review():
            _, decision = review_output(command.question, serialized)
            # A prose fallback cannot safely replace a typed nutrition/plan object.
            if decision.outcome != "allow":
                decision = decision.model_copy(update={"outcome": "refuse"})
            context.record("SAFETY_DECIDED", context, {
                "outcome": decision.outcome, "risk_category": decision.risk_category,
                "rule_version": SAFETY_RULE_VERSION,
            })
            if decision.outcome != "allow":
                raise SafetyRefusal(decision, command.question)
            return output

        reviewed = await context.step("safety_reviewer", review)
        return await context.step("result_projector", lambda: AgentResult(
            answer_markdown="", intent=command.operation, trace={},
            tool_results={"structured": StructuredModelResult(reviewed, result.model, result.usage)},
            sources=(), model=result.model,
        ))


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
