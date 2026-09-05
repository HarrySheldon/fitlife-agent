from __future__ import annotations
import json
from collections.abc import Mapping

def writer_payload(state: Mapping[str, object]) -> dict[str, object]:
    return {"user_query": state.get("user_query", ""), "context_metadata": state.get("context_metadata", {}),
            "intent": state.get("intent", ""), "profile": state.get("profile", {}),
            "tool_results": state.get("tool_results", {}), "retrieved_docs": state.get("retrieved_docs", []),
            "validation_result": state.get("validation_result", {})}

def incremental_writer_payload(state: Mapping[str, object], initial_results: Mapping[str, object]) -> dict[str, object]:
    payload = writer_payload(state)
    current = payload["tool_results"] if isinstance(payload["tool_results"], Mapping) else {}
    payload["tool_results"] = {key: value for key, value in current.items() if key not in initial_results or initial_results[key] != value}
    return payload

def serialized_payload(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)
