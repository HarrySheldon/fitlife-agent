from __future__ import annotations

import json
from typing import Any

from backend.agent.planner import PlannerRoute
from backend.infrastructure.model_gateway.openai_responses import (
    PLANNER_INSTRUCTIONS,
    WRITER_INSTRUCTIONS,
    _model_ids,
    _probe_tool,
    _writer_payload,
)


class OpenAIChatCompletionsAdapter:
    def __init__(self, *, client: Any, model: str) -> None:
        self.client = client
        self.model = model

    def plan_route(self, question: str) -> PlannerRoute:
        response = self.client.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": PLANNER_INSTRUCTIONS},
                {"role": "user", "content": question},
            ],
            response_format=PlannerRoute,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("Planner response did not contain structured output")
        return PlannerRoute.model_validate(parsed)

    def write_answer(self, state: dict) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": WRITER_INSTRUCTIONS},
                {
                    "role": "user",
                    "content": json.dumps(_writer_payload(state), ensure_ascii=False),
                },
            ],
        )
        text = str(response.choices[0].message.content or "").strip()
        if not text:
            raise ValueError("Writer response did not contain text")
        return text

    def list_models(self) -> list[str]:
        return _model_ids(self.client.models.list())

    def probe_tool_call(self) -> None:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": "Call connection_probe with ok=true."}],
            tools=[{"type": "function", "function": _probe_tool()}],
            tool_choice={"type": "function", "function": {"name": "connection_probe"}},
        )
        tool_calls = response.choices[0].message.tool_calls or []
        if not any(call.function.name == "connection_probe" for call in tool_calls):
            raise ValueError("Model did not return the required tool call")
