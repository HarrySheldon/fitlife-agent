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
    _probe_timeout,
    _valid_probe_arguments,
)
from backend.agent.model_payloads import writer_payload_for_model
from backend.application.ports.model_call_context import model_timeout_options, model_output_limit
from backend.domain.model_connection_probe import ConnectionBusinessSample, check_business_sample
from backend.infrastructure.model_gateway.structured_json import json_instructions, parse_json_output


class OpenAIChatCompletionsAdapter:
    def __init__(self, *, client: Any, model: str, structured_mode: str = "native",
                 max_tokens_field: str = "max_completion_tokens") -> None:
        self.client = client
        self.model = model
        self.structured_mode = structured_mode
        self.max_tokens_field = max_tokens_field

    def plan_route(self, question: str) -> PlannerRoute:
        from backend.agent.tasks.input_contracts import build_review_input
        question = build_review_input(question=question, draft="").question
        if self.structured_mode == "json":
            return self.parse_structured(instructions=PLANNER_INSTRUCTIONS, input_text=question,
                response_model=PlannerRoute).output
        response = self.client.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": PLANNER_INSTRUCTIONS},
                {"role": "user", "content": question},
            ],
            response_format=PlannerRoute,
            **model_timeout_options(),
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("Planner response did not contain structured output")
        return PlannerRoute.model_validate(parsed)

    def write_answer(self, state: dict) -> str:
        # Same ceiling as the Responses adapter, under this protocol's parameter name.
        limit = model_output_limit.get()
        output_options = {self.max_tokens_field: limit} if limit is not None else {}
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": WRITER_INSTRUCTIONS},
                {
                    "role": "user",
                    # The sanitised payload when the context guard produced one;
                    # rebuilding it from the raw state would send data the guard never
                    # saw.
                    "content": json.dumps(writer_payload_for_model(state), ensure_ascii=False),
                },
            ],
            **output_options,
            **model_timeout_options(),
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
        limit = model_output_limit.get()
        output_options = {self.max_tokens_field: limit} if limit is not None else {}
        if self.structured_mode == "json":
            response = self.client.chat.completions.create(model=self.model, messages=[
                {"role": "system", "content": json_instructions(instructions, response_model)},
                {"role": "user", "content": input_text}], **output_options, **model_timeout_options())
            parsed = parse_json_output(response.choices[0].message.content or "", response_model)
            return StructuredModelResult(output=parsed, model=str(getattr(response, "model", None) or self.model),
                usage=_chat_usage(getattr(response, "usage", None)))
        response = self.client.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": input_text},
            ],
            response_format=response_model,
            **output_options,
            **model_timeout_options(),
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
        return _model_ids(self.client.models.list(**model_timeout_options()))

    def close(self) -> None:
        self.client.close()

    def probe_generation(self) -> dict[str, int] | None:
        response = self.client.chat.completions.create(model=self.model,
            messages=[{"role": "user", "content": "Reply with OK."}],
            **{self.max_tokens_field: 128}, **_probe_timeout())
        if not str(response.choices[0].message.content or "").strip():
            raise ValueError("Model did not return nonempty text")
        return _chat_usage(getattr(response, "usage", None)) or None

    def probe_structured(self) -> dict[str, int] | None:
        token = model_output_limit.set(128)
        try:
            result = self.parse_structured(instructions="Extract the food, amount and unit from the synthetic input.",
                input_text="oats 40 g", response_model=ConnectionBusinessSample)
            check_business_sample(result.output)
            return result.usage or None
        finally:
            model_output_limit.reset(token)

    def probe_tool_call(self) -> dict[str, int] | None:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": "Call connection_probe with ok=true."}],
            tools=[{"type": "function", "function": _probe_tool()}],
            tool_choice={"type": "function", "function": {"name": "connection_probe"}},
            max_completion_tokens=128,
            **_probe_timeout(),
        )
        tool_calls = response.choices[0].message.tool_calls or []
        if not any(call.function.name == "connection_probe"
                   and _valid_probe_arguments(getattr(call.function, "arguments", "")) for call in tool_calls):
            raise ValueError("Model did not return the required tool call")
        return _chat_usage(getattr(response, "usage", None)) or None


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
