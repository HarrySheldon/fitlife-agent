"""Authoritative run state, append-only diagnostics, and recovery metadata."""
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Mapping, Protocol
import math
import re

from backend.agent.contracts import AgentRunSnapshot

TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "timed_out"})
ERROR_CODES = frozenset({"INTERNAL_ERROR", "MODEL_AUTH_FAILED", "MODEL_NOT_FOUND", "MODEL_TERMINAL_ERROR",
    "MODEL_CONNECTION_FAILED", "MODEL_TIMEOUT", "MODEL_QUOTA_EXHAUSTED", "MODEL_SAFETY_REFUSAL",
    "MODEL_TRANSIENT_ERROR", "MODEL_INVALID_REQUEST", "RUN_CANCELLED", "RUN_TIMED_OUT",
    "RUN_BUDGET_EXCEEDED", "AI_NOT_CONFIGURED", "CREDENTIAL_STORE_UNAVAILABLE", "SAFETY_REFUSAL", "AGENT_RATE_LIMITED", "CONFIGURATION_INVALID"})
EVENT_TYPES = frozenset({
    "RUN_ACCEPTED", "RUN_STARTED", "STEP_STARTED", "STEP_RETRY_SCHEDULED",
    "STEP_SUCCEEDED", "STEP_FAILED", "TOOL_STARTED", "TOOL_FINISHED",
    "SAFETY_DECIDED", "RUN_CANCEL_REQUESTED", "RUN_SUCCEEDED", "RUN_FAILED",
    "RUN_CANCELLED", "RUN_TIMED_OUT",
})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class VersionConflict(RuntimeError):
    pass


class InvalidTransition(RuntimeError):
    pass


def safe_payload(payload: Mapping[str, object]) -> dict:
    """Reject unknown fields and free-form text; never stringify exceptions."""
    allowed = {"duration_ms", "delay_ms", "input_tokens", "output_tokens", "tool_calls", "internal_error_id", "error_code", "error_type", "outcome", "tool", "risk_category", "rule_version"}
    result = {}
    for key, value in payload.items():
        if key not in allowed:
            raise ValueError("Unsupported event payload field")
        if key in {"duration_ms", "delay_ms", "input_tokens", "output_tokens", "tool_calls"}:
            if type(value) not in (int, float) or value < 0 or not math.isfinite(value):
                raise ValueError("Invalid event metric")
        elif key == "error_code" and value not in ERROR_CODES:
            raise ValueError("Invalid error code")
        elif key == "error_type" and value not in {"transient", "authentication", "invalid_input", "quota", "safety", "cancelled", "timeout", "budget", "internal"}:
            raise ValueError("Invalid error category")
        elif key == "outcome" and value not in {"succeeded", "failed", "cancelled", "timed_out", "allow", "rewrite", "refuse"}:
            raise ValueError("Invalid outcome")
        elif key == "risk_category" and value not in {"low", "emergency", "self_harm", "medical", "extreme_diet", "dangerous_training", "input_limit", "review_unavailable", "out_of_scope"}:
            raise ValueError("Invalid safety risk")
        elif key == "rule_version" and value != "fitlife-safety-v1":
            raise ValueError("Invalid safety rule version")
        elif key == "internal_error_id" and (not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{32}", value) is None):
            raise ValueError("Invalid event identifier")
        elif key == "tool" and value not in {"plan_route_model", "write_answer_model", "load_profile", "analyze_meals", "analyze_workouts", "retrieve_knowledge", "generate_weekly_report", "generate_next_week_plan", "validate_plan", "other"}:
            raise ValueError("Invalid tool identifier")
        result[key] = value
    return result


@dataclass(frozen=True)
class RunEvent:
    run_id: str
    seq: int
    event_type: str
    step: str | None = None
    attempt: int | None = None
    occurred_at: str = field(default_factory=utc_now)
    payload: Mapping[str, object] = field(default_factory=dict)


def next_snapshot(current, proposed, event_type):
    if proposed.version != current.version:
        raise VersionConflict("Stale run version")
    if current.status in TERMINAL_STATUSES:
        raise InvalidTransition("Run is already terminal")
    immutable = ("run_id", "request_id", "user_id", "operation", "created_at", "deadline_at", "policy_version", "policy_snapshot_json")
    if any(getattr(current, name) != getattr(proposed, name) for name in immutable):
        raise InvalidTransition("Immutable run metadata changed")
    expected = {"RUN_STARTED": "running", "RUN_SUCCEEDED": "succeeded", "RUN_FAILED": "failed", "RUN_CANCELLED": "cancelled", "RUN_TIMED_OUT": "timed_out"}
    if event_type not in EVENT_TYPES or event_type == "RUN_ACCEPTED":
        raise InvalidTransition("Invalid run event")
    if proposed.status != expected.get(event_type, current.status):
        raise InvalidTransition("Event and status disagree")
    if event_type == "RUN_STARTED" and current.status != "accepted":
        raise InvalidTransition("Run already started")
    if event_type not in expected and current.status != "running":
        raise InvalidTransition("Step events require a running run")
    return replace(proposed, version=current.version + 1)


class AgentRunRepository(Protocol):
    def create(self, run: AgentRunSnapshot) -> AgentRunSnapshot: ...
    def get(self, run_id: str, user_id: str | None) -> AgentRunSnapshot: ...
    def update(self, run: AgentRunSnapshot, event_type: str, payload: Mapping[str, object] = {}) -> AgentRunSnapshot: ...
    def events(self, run_id: str, user_id: str | None) -> tuple[RunEvent, ...]: ...


@dataclass(frozen=True)
class Checkpoint:
    run_id: str
    name: str
    state: Mapping[str, object]
    version: int = 1


class CheckpointStore(Protocol):
    def save(self, run_id: str, user_id: str | None, name: str, state: Mapping[str, object]) -> Checkpoint: ...
    def get(self, run_id: str, user_id: str | None, name: str) -> Checkpoint: ...


def safe_checkpoint(state):
    if "schema_version" in state:
        from backend.agent.checkpoints import restore_planner_state
        restored = restore_planner_state(state)
        return {"schema_version": 1, "next_step": "profile_loader", "route": restored["tool_requests"]}
    # Health data and model content intentionally have no representation here.
    if set(state) - {"completed", "attempt"} or ("completed" in state and type(state["completed"]) is not bool) or ("attempt" in state and (type(state["attempt"]) is not int or state["attempt"] < 0)):
        raise ValueError("Only minimal step completion metadata can be checkpointed")
    return dict(state)
