from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Literal, TypeVar

from backend.agent.contracts import AgentCommand, AgentResult, AgentWorkflow

T = TypeVar("T")


class RuntimeContext:
    def __init__(self) -> None:
        self.completed_steps: list[str] = []
        self.completed_tools: list[str] = []

    async def step(self, name: str, operation: Callable[[], Awaitable[T] | T]) -> T:
        value = operation()
        result = await value if inspect.isawaitable(value) else value
        self.completed_steps.append(name)
        return result

    async def tool(
        self,
        name: str,
        replay: Literal["safe", "never"],
        operation: Callable[[], Awaitable[T] | T],
    ) -> T:
        del replay
        value = operation()
        result = await value if inspect.isawaitable(value) else value
        self.completed_tools.append(name)
        return result


class AgentRuntime:
    async def execute(self, command: AgentCommand, workflow: AgentWorkflow) -> AgentResult:
        result = await workflow.execute(command, RuntimeContext())
        return result.with_request_id()

    def execute_sync(self, command: AgentCommand, workflow: AgentWorkflow) -> AgentResult:
        return asyncio.run(self.execute(command, workflow))
