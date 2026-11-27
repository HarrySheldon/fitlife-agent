"""Trajectory first-error step attribution over runtime events and run records."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from backend.task_evaluation.report import RunRecord

ATTRIBUTION_CATEGORIES = frozenset({
    "input_safety",
    "tool_execution",
    "retrieval_empty",
    "protocol_error",
    "output_safety",
    "invariant_mismatch",
    "timeout_or_budget",
    "unknown",
})

_FAILURE_EVENTS = frozenset({
    "STEP_FAILED",
    "TOOL_FINISHED",
    "TOOL_DENIED",
    "SAFETY_REFUSED",
    "PROTOCOL_FAILED",
    "RUN_FAILED",
    "RUN_TIMED_OUT",
    "RUN_CANCELLED",
})


@dataclass(frozen=True)
class FirstErrorAttribution:
    case_id: str
    run_id: str | None
    error_category: str
    step_index: int | None
    step_name: str | None
    event_type: str
    summary: str


def _classify_event(event: Mapping[str, Any], *, fallback_error_class: str | None) -> str:
    event_type = str(event.get("event_type") or "")
    step_name = str(event.get("step") or event.get("step_name") or "").lower()
    payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
    error_type = str(event.get("error_type") or payload.get("error_type") or "").lower()
    error_code = str(event.get("error_code") or payload.get("error_code") or "").lower()
    outcome = str(event.get("outcome") or event.get("status") or payload.get("outcome") or "").lower()

    if event_type == "SAFETY_REFUSED" or error_type == "safety" or "safety_refus" in error_code:
        if any(tok in step_name for tok in ("output", "review", "writer", "render")):
            return "output_safety"
        return "input_safety"
    if event_type == "PROTOCOL_FAILED" or "protocol" in error_code or "schema" in error_code:
        return "protocol_error"
    if event_type == "RUN_TIMED_OUT" or error_type in {"timeout", "budget", "quota"}:
        return "timeout_or_budget"
    if "retriev" in step_name and any(tok in error_code for tok in ("empty", "insufficient", "no_matching")):
        return "retrieval_empty"
    if event_type in {"TOOL_FINISHED", "TOOL_DENIED"} or step_name.startswith("tool") or bool(event.get("agent_tool") or payload.get("agent_tool")):
        if outcome in {"failed", "denied", "error", "timed_out"} or error_type or error_code:
            return "tool_execution"
    if event_type in {"STEP_FAILED", "RUN_FAILED", "RUN_CANCELLED"}:
        if any(tok in error_code for tok in ("output", "ungrounded")):
            return "output_safety"
        if any(tok in step_name for tok in ("output", "review")):
            return "output_safety"
        if "protocol" in step_name:
            return "protocol_error"
        return "tool_execution" if payload.get("agent_tool") or payload.get("tool") else "unknown"
    if fallback_error_class in {"timed_out", "deadline_exceeded"}:
        return "timeout_or_budget"
    return "unknown"


def _is_failure_event(event: Mapping[str, Any]) -> bool:
    event_type = str(event.get("event_type") or "")
    payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
    outcome = str(event.get("outcome") or event.get("status") or payload.get("outcome") or "").lower()
    error_code = event.get("error_code") or payload.get("error_code")
    error_type = event.get("error_type") or payload.get("error_type")

    if event_type in {"STEP_FAILED", "TOOL_DENIED", "SAFETY_REFUSED", "PROTOCOL_FAILED", "RUN_FAILED", "RUN_TIMED_OUT", "RUN_CANCELLED"}:
        return True
    if event_type in _FAILURE_EVENTS and (
        outcome in {"failed", "denied", "refuse", "timed_out", "cancelled", "error"}
        or bool(error_code)
        or bool(error_type)
    ):
        return True
    if outcome in {"failed", "denied", "refuse", "timed_out", "cancelled", "error"}:
        return True
    return False


def _ordered_events(events: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    indexed = list(enumerate(events))
    indexed.sort(key=lambda pair: (
        int(pair[1].get("seq")) if isinstance(pair[1].get("seq"), int) else pair[0],
        pair[0],
    ))
    return [pair[1] for pair in indexed]


def attribute_first_error(
    record: RunRecord,
    events: Sequence[Mapping[str, Any]] | None = None,
) -> FirstErrorAttribution | None:
    """Identify the earliest error-causing step/category for a failed ``RunRecord``."""
    if record.success:
        return None

    details = record.details if isinstance(record.details, Mapping) else {}
    run_ids = details.get("run_ids")
    run_id = str(run_ids[0]) if isinstance(run_ids, (list, tuple)) and run_ids else None
    raw_events = list(events) if events is not None else list(details.get("events") or ())

    for idx, event in enumerate(_ordered_events(raw_events)):
        if not isinstance(event, Mapping) or not _is_failure_event(event):
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
        step_name = event.get("step") or event.get("step_name")
        step_index = event.get("step_index")
        if step_index is None:
            step_index = payload.get("step_index")
        if step_index is None and isinstance(event.get("seq"), int):
            step_index = int(event["seq"])
        elif step_index is None:
            step_index = idx
        event_type = str(event.get("event_type") or "STEP_FAILED")
        category = _classify_event(event, fallback_error_class=record.error_class)
        code = event.get("error_code") or payload.get("error_code") or event.get("outcome") or event.get("status")
        summary = f"{event_type}:{step_name or 'unknown'}:{code or category}"
        return FirstErrorAttribution(
            case_id=record.case_id,
            run_id=str(event.get("run_id") or run_id) if (event.get("run_id") or run_id) else None,
            error_category=category,
            step_index=int(step_index) if isinstance(step_index, int) else idx,
            step_name=str(step_name) if step_name is not None else None,
            event_type=event_type,
            summary=summary,
        )

    failed_fields = [str(f) for f in (details.get("failed_fields") or ()) if f]
    err_cls = str(record.error_class or "")
    if err_cls in {"timed_out", "deadline_exceeded"} or "turn_not_terminal" in failed_fields:
        category = "timeout_or_budget"
    elif "safety" in err_cls.lower():
        category = "input_safety"
    elif failed_fields:
        category = "invariant_mismatch"
    else:
        category = "unknown"

    summary = f"{err_cls or 'failed'}:{','.join(failed_fields) if failed_fields else category}"
    return FirstErrorAttribution(
        case_id=record.case_id,
        run_id=run_id,
        error_category=category,
        step_index=None,
        step_name=failed_fields[0] if failed_fields else None,
        event_type=err_cls or "RUN_FAILED",
        summary=summary,
    )
