from __future__ import annotations

import json
from typing import Any

from backend.agent.planner import PlannerRoute
from backend.config import Settings, get_settings


PLANNER_INSTRUCTIONS = """You are FitLife Coach Agent's planner.
Classify the user's question into the project intent taxonomy and mark which capabilities are required.
Return only the structured PlannerRoute fields. Do not answer the user."""

WRITER_INSTRUCTIONS = """You are FitLife Coach Agent's report writer.
Write a concise Markdown answer using only the provided profile, tool results, retrieved sources, and validation result.
Do not provide medical diagnosis. If generating a personalized plan, include a short lifestyle disclaimer."""


class OpenAIResponsesAdapter:
    def __init__(self, *, client: Any, model: str) -> None:
        self.client = client
        self.model = model

    def plan_route(self, question: str) -> PlannerRoute:
        response = self.client.responses.parse(
            model=self.model,
            instructions=PLANNER_INSTRUCTIONS,
            input=question,
            text_format=PlannerRoute,
        )
        parsed = _extract_parsed_output(response)
        if parsed is None:
            raise ValueError("Planner response did not contain structured output")
        return PlannerRoute.model_validate(parsed)

    def write_answer(self, state: dict) -> str:
        response = self.client.responses.create(
            model=self.model,
            instructions=WRITER_INSTRUCTIONS,
            input=json.dumps(_writer_payload(state), ensure_ascii=False),
        )
        text = str(getattr(response, "output_text", "")).strip()
        if not text:
            raise ValueError("Writer response did not contain text")
        return text

    def list_models(self) -> list[str]:
        return _model_ids(self.client.models.list())

    def probe_tool_call(self) -> None:
        response = self.client.responses.create(
            model=self.model,
            instructions="Call connection_probe with ok=true.",
            input="Test the configured Agent tool-calling capability.",
            tools=[{"type": "function", **_probe_tool()}],
            tool_choice={"type": "function", "name": "connection_probe"},
        )
        if not any(
            getattr(item, "type", None) == "function_call"
            and getattr(item, "name", None) == "connection_probe"
            for item in getattr(response, "output", [])
        ):
            raise ValueError("Model did not return the required tool call")


def build_model_gateway(
    *,
    settings: Settings | None = None,
    client: Any | None = None,
) -> OpenAIResponsesAdapter | None:
    settings = settings or get_settings()
    if not settings.llm_enabled or not settings.openai_api_key:
        return None

    if client is None:
        try:
            from openai import OpenAI
        except ImportError:
            return None

        kwargs: dict[str, str] = {"api_key": settings.openai_api_key}
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url
        client = OpenAI(**kwargs)

    return OpenAIResponsesAdapter(client=client, model=settings.openai_model)


def _extract_parsed_output(response: Any) -> Any | None:
    for output in getattr(response, "output", []):
        if getattr(output, "type", None) != "message":
            continue
        for item in getattr(output, "content", []):
            if getattr(item, "type", None) == "output_text" and getattr(item, "parsed", None) is not None:
                return item.parsed
    return None


def _writer_payload(state: dict) -> dict:
    return {
        "user_query": state.get("user_query", ""),
        "intent": state.get("intent", ""),
        "profile": state.get("profile", {}),
        "tool_results": state.get("tool_results", {}),
        "retrieved_docs": state.get("retrieved_docs", []),
        "validation_result": state.get("validation_result", {}),
    }


def _model_ids(response: Any) -> list[str]:
    return sorted(
        {
            str(item.id).strip()
            for item in getattr(response, "data", [])
            if getattr(item, "id", None)
        }
    )


def _probe_tool() -> dict:
    return {
        "name": "connection_probe",
        "description": "Confirm that required Agent tool calls are supported.",
        "parameters": {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
        "strict": True,
    }
