from dataclasses import dataclass
from typing import Protocol
from backend.agent.decision import AgentDecision


@dataclass(frozen=True)
class AgentDecisionRequest:
    instructions: str
    messages: tuple[dict, ...]
    tool_descriptions: tuple[dict, ...]
    max_output_tokens: int = 2048


@dataclass(frozen=True)
class AgentDecisionResult:
    decision: AgentDecision
    model: str
    usage: dict[str, int]


class AgentDecisionGateway(Protocol):
    model: str

    def decide(self, request: AgentDecisionRequest) -> AgentDecisionResult: ...
