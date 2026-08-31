from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal, Mapping, Protocol
from uuid import uuid4

if TYPE_CHECKING:
    from backend.agent.runtime import RuntimeContext

AgentOperation = Literal["chat", "coach_action", "plan_review", "weekly_review", "evaluation"]


@dataclass(frozen=True)
class AgentCommand:
    operation: AgentOperation
    question: str
    user_id: str | None
    surface: str | None = None
    context_date: str | None = None
    initial_tool_results: Mapping[str, object] = field(default_factory=dict)
    initial_tool_calls: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentResult:
    answer_markdown: str
    intent: str
    trace: Mapping[str, object]
    tool_results: Mapping[str, object]
    sources: tuple[Mapping[str, object], ...]
    model: str
    request_id: str = ""

    def with_request_id(self) -> AgentResult:
        return self if self.request_id else replace(self, request_id=uuid4().hex)

    def to_dict(self) -> dict[str, object]:
        return {
            "answer_markdown": self.answer_markdown,
            "intent": self.intent,
            "trace": dict(self.trace),
            "tool_results": dict(self.tool_results),
            "sources": [dict(source) for source in self.sources],
            "model": self.model,
            "request_id": self.request_id,
        }


class AgentWorkflow(Protocol):
    async def execute(self, command: AgentCommand, context: RuntimeContext) -> AgentResult: ...
