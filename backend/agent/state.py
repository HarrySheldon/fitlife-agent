from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict, total=False):
    messages: list[dict]
    user_query: str
    intent: str
    profile: dict
    tool_requests: dict
    tool_calls: list[str]
    tool_results: dict
    retrieval_query: str
    retrieved_docs: list[dict]
    draft_answer: str
    validation_result: dict
    final_answer: str
    trace: dict
