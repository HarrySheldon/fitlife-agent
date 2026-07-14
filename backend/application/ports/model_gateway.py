from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.agent.planner import PlannerRoute


@runtime_checkable
class ModelGateway(Protocol):
    model: str

    def plan_route(self, question: str) -> PlannerRoute: ...

    def write_answer(self, state: dict) -> str: ...


@runtime_checkable
class ConfigurableModelGateway(ModelGateway, Protocol):
    def list_models(self) -> list[str]: ...

    def probe_tool_call(self) -> None: ...
