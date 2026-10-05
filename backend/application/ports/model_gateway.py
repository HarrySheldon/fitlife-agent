from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from backend.application.ports.structured_model_gateway import (
    StructuredModelGateway,
)

if TYPE_CHECKING:
    # Typing only. Importing the contract at runtime would pull the analysis
    # registry into every consumer of this package and close an import cycle.
    from backend.agent.planner import PlannerRoute


@runtime_checkable
class ModelGateway(Protocol):
    model: str

    def plan_route(self, question: str) -> PlannerRoute: ...

    def write_answer(self, state: dict) -> str: ...


@runtime_checkable
class ConfigurableModelGateway(ModelGateway, StructuredModelGateway, Protocol):
    def list_models(self) -> list[str]: ...

    def probe_tool_call(self) -> None: ...
