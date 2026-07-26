from __future__ import annotations

import json
from typing import Any

from backend.agent.planner import PlannerRoute
from backend.application.ports.structured_model_gateway import (
    StructuredModelResult,
    StructuredOutput,
)
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

    def parse_structured(
        self,
        *,
        instructions: str,
        input_text: str,
        response_model: type[StructuredOutput],
    ) -> StructuredModelResult:
        response = self.client.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": input_text},
            ],
            response_format=response_model,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("Response did not contain structured output")
        return StructuredModelResult(
            output=response_model.model_validate(parsed),
            model=str(getattr(response, "model", None) or self.model),
            usage=_chat_usage(getattr(response, "usage", None)),
        )

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


def _chat_usage(value: Any) -> dict[str, int]:
    if value is None:
        return {}
    fields = {
        "input_tokens": getattr(value, "prompt_tokens", None),
        "output_tokens": getattr(value, "completion_tokens", None),
        "total_tokens": getattr(value, "total_tokens", None),
    }
    return {
        key: int(item)
        for key, item in fields.items()
        if isinstance(item, int) and not isinstance(item, bool) and item >= 0
    }
