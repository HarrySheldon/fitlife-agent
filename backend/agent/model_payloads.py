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


def writer_payload_for_model(state: Mapping[str, object]) -> dict[str, object]:
    """The payload to send: the sanitised one once the context guard has produced it.

    The guard sanitises the payload and records it on the state, but the adapters used
    to rebuild it here from the raw state and send that instead - the check ran on one
    payload and a different payload went on the wire, so an instruction hidden in a
    record still reached the model. Preferring the recorded payload keeps the check on
    what the provider actually receives.

    The fallback keeps callers outside the agent pipeline working; they have no
    context to sanitise.
    """
    recorded = state.get("writer_payload")
    if isinstance(recorded, Mapping) and recorded:
        return dict(recorded)
    return writer_payload(state)
