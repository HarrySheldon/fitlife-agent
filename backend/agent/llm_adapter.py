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
    def __init__(self, *, client: Any, model: str):
        self.client = client
        self.model = model

    def plan_route(self, question: str) -> PlannerRoute | None:
        response = self.client.responses.parse(
            model=self.model,
            instructions=PLANNER_INSTRUCTIONS,
            input=question,
            text_format=PlannerRoute,
        )
        parsed = _extract_parsed_output(response)
        if parsed is None:
            return None
        return PlannerRoute.model_validate(parsed)

    def write_answer(self, state: dict) -> str | None:
        response = self.client.responses.create(
            model=self.model,
            instructions=WRITER_INSTRUCTIONS,
            input=json.dumps(_writer_payload(state), ensure_ascii=False),
        )
        text = str(getattr(response, "output_text", "")).strip()
        return text or None


def build_llm_adapter(
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


def try_plan_route_with_llm(
    question: str,
    *,
    adapter: OpenAIResponsesAdapter | Any | None = None,
) -> PlannerRoute | None:
    adapter = adapter if adapter is not None else build_llm_adapter()
    if adapter is None:
        return None
    try:
        return adapter.plan_route(question)
    except Exception:
        return None


def try_write_answer_with_llm(
    state: dict,
    *,
    adapter: OpenAIResponsesAdapter | Any | None = None,
) -> str | None:
    adapter = adapter if adapter is not None else build_llm_adapter()
    if adapter is None:
        return None
    try:
        return adapter.write_answer(state)
    except Exception:
        return None


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
