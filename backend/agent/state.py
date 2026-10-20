from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict, total=False):
    operation: str
    messages: list[dict]
    recent_history: list[dict]
    user_query: str
    current_user_id: str | None
    surface: str | None
    coach_action: str | None
    context_date: str | None
    context_metadata: dict
    answer_language: str
    answer_mode: str
    intent: str
    profile: dict
    writer_payload: dict
    writer_payload_owner: str | None
    tool_requests: dict
    tool_calls: list[str]
    tool_results: dict
    initial_tool_results_snapshot: dict
    retrieval_query: str
    retrieved_docs: list[dict]
    draft_answer: str
    validation_result: dict
    final_answer: str
    llm_used: bool
    llm_answer_used: bool
    trace: dict
