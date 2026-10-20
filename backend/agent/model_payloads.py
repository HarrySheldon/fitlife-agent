from __future__ import annotations
import json
from collections.abc import Mapping
from backend.agent.tasks.input_contracts import build_chat_input, sanitize_stage_input, ChatInput
from backend.domain.coach_answer import DEFAULT_LANGUAGE


def answer_language_for(state: Mapping[str, object]) -> str:
    """The language this run must answer in.

    Order: the resolved value the workflow stored, then the account preference that
    travelled in `context_metadata`, then the app default. Never the question text.
    """
    explicit = state.get("answer_language")
    if isinstance(explicit, str) and explicit:
        return explicit
    metadata = state.get("context_metadata")
    if isinstance(metadata, Mapping):
        account = metadata.get("language")
        if isinstance(account, str) and account:
            return account
    return DEFAULT_LANGUAGE


def answer_mode_for(state: Mapping[str, object]) -> str:
    mode = state.get("answer_mode")
    return mode if mode in ("brief", "detailed") else "brief"


def writer_payload(state: Mapping[str, object]) -> dict[str, object]:
    return build_chat_input(current_question=state.get("user_query", ""),
        approved_intent=state.get("intent", ""), context_metadata=state.get("context_metadata", {}),
        nutrient_targets_and_restrictions=state.get("profile", {}),
        analysis_summaries=state.get("tool_results", {}), sources=state.get("retrieved_docs", []),
        validation=state.get("validation_result", {}), sanitize=False,
        answer_language=answer_language_for(state),
        answer_mode=answer_mode_for(state), recent_history=[{"role": item["role"], "body": item["body"]} for item in state.get("recent_history", ())]).model_dump()

def incremental_writer_payload(state: Mapping[str, object], initial_results: Mapping[str, object]) -> dict[str, object]:
    # Providers are stateless: unchanged initial facts still belong in every call.
    # The stage projection bounds disclosure and the caller budgets these bytes.
    return writer_payload(state)

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
    owner = state.get("current_user_id")
    if isinstance(recorded, Mapping) and recorded and state.get("writer_payload_owner") == owner:
        # Revalidation keeps direct adapter callers from injecting extra cache fields.
        return sanitize_stage_input(ChatInput.model_validate(writer_payload(recorded))).model_dump()
    return sanitize_stage_input(ChatInput.model_validate(writer_payload(state))).model_dump()
