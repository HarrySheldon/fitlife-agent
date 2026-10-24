"""Closed attempt accounting and explicit token provenance.

Two rules govern this module, and both exist to keep the evaluation report
falsifiable:

* a quantity that was not measured is ``None`` with an explicit ``unknown``
  source -- never ``0``, and never a mock character estimate standing in for a
  provider number;
* every physical attempt is opened *before* the operation starts and closed with
  a terminal state, so "started but never finished" stays distinguishable from
  "was never called". A cancellation that cannot clean up leaves the attempt
  open on purpose: the event log then shows the gap instead of hiding it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Mapping
from uuid import uuid4

from backend.task_evaluation.provenance import fingerprint

USAGE_SOURCES = frozenset({"provider", "mock_estimate", "unknown"})
# A provider total and a local estimate are different evidence. They are stored
# side by side and never substituted for one another.
MEASURED_USAGE_SOURCES = frozenset({"provider", "mock_estimate"})

ATTEMPT_KINDS = frozenset(
    {
        "physical_model",
        "physical_handler",
        "transport_retry",
        "logical_proposal",
        "cache_hit",
    }
)
ATTEMPT_STATES = frozenset({"started", "completed", "failed", "cancelled", "incomplete"})
TERMINAL_ATTEMPT_STATES = frozenset({"completed", "failed", "cancelled", "incomplete"})


class AttemptKind:
    """Named constants; a plain string keeps the event payload JSON-native."""

    PHYSICAL_MODEL = "physical_model"
    PHYSICAL_HANDLER = "physical_handler"
    TRANSPORT_RETRY = "transport_retry"
    LOGICAL_PROPOSAL = "logical_proposal"
    CACHE_HIT = "cache_hit"


class AttemptState:
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INCOMPLETE = "incomplete"

# Settings that define the task itself. Changing one makes previous numbers
# incomparable: a different engine, a different safety posture, a different
# answer contract is a different experiment.
INVARIANT_SETTINGS = (
    "llm_enabled",
    "safety_review_mode",
    "safety_grounding_mode",
    "interactive_entry_enabled",
    "entry_task_ttl_days",
    "coach_conversations_enabled",
    "coach_agent_mode",
    "plan_adjustment_tasks_enabled",
    "plan_storage_mode",
    "plan_candidate_ttl_minutes",
    "answer_language",
    "answer_mode",
)
# Settings that describe the treatment under test. Changing one is the whole
# point of a paired comparison, so it must not look like a different task.
TREATMENT_SETTINGS = (
    "task_execution_strategy",
    "context_policy_version",
    "prefetch_enabled",
    "task_cache_enabled",
)


def _count(value: object, *, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


@dataclass(frozen=True)
class UsageMeasurement:
    """Token usage with an explicit provenance.

    ``cached_input_tokens`` is a subset of ``input_tokens`` and is deliberately
    excluded from ``total_tokens``: a cached prompt token is still billed input
    in most contracts, and double counting it would inflate the baseline.
    """

    source: str
    input_tokens: int | None
    output_tokens: int | None
    cached_input_tokens: int | None

    def __post_init__(self) -> None:
        if self.source not in USAGE_SOURCES:
            raise ValueError("Unregistered usage source")
        if self.source == "unknown":
            if any(
                value is not None
                for value in (self.input_tokens, self.output_tokens, self.cached_input_tokens)
            ):
                raise ValueError("Unknown usage must not carry a number")
            return
        for name in ("input_tokens", "output_tokens"):
            value = getattr(self, name)
            if value is None:
                raise ValueError(f"{name} is required for a measured usage")
            _count(value, name=name)
        if self.cached_input_tokens is not None:
            _count(self.cached_input_tokens, name="cached_input_tokens")
            if self.cached_input_tokens > self.input_tokens:
                raise ValueError("cached_input_tokens must be a subset of input_tokens")

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens

    @property
    def measured(self) -> bool:
        return self.source in MEASURED_USAGE_SOURCES


def unknown_usage() -> UsageMeasurement:
    return UsageMeasurement(source="unknown", input_tokens=None, output_tokens=None,
                            cached_input_tokens=None)


@dataclass(frozen=True)
class AttemptRecord:
    """One physical attempt, from its trusted start to its terminal state."""

    attempt_id: str
    kind: str
    state: str
    tool: str | None = None
    usage: UsageMeasurement = field(default_factory=unknown_usage)
    started_at: float | None = None
    finished_at: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in ATTEMPT_KINDS:
            raise ValueError("Unregistered attempt kind")
        if self.state not in ATTEMPT_STATES:
            raise ValueError("Unregistered attempt state")


@dataclass(frozen=True)
class AttemptSummary:
    started: int
    completed: int
    failed: int
    cancelled: int
    incomplete: int
    unknown_usage: int
    known_total_tokens: int
    by_kind: Mapping[str, int] = field(default_factory=dict)


def summarize_attempts(records) -> AttemptSummary:
    records = tuple(records)
    states = {state: 0 for state in ATTEMPT_STATES}
    kinds: dict[str, int] = {}
    unknown = 0
    known = 0
    for record in records:
        states[record.state] += 1
        kinds[record.kind] = kinds.get(record.kind, 0) + 1
        if record.state == "completed":
            total = record.usage.total_tokens
            if total is None:
                unknown += 1
            else:
                known += total
    return AttemptSummary(
        started=len(records),
        completed=states["completed"],
        failed=states["failed"],
        cancelled=states["cancelled"],
        incomplete=states["incomplete"],
        unknown_usage=unknown,
        known_total_tokens=known,
        by_kind=kinds,
    )


class AttemptLedger:
    """Opens attempts before they start and refuses to leave one unlabelled."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic, id_factory=None):
        self._clock = clock
        self._new_id = id_factory or (lambda: uuid4().hex)
        self._records: dict[str, AttemptRecord] = {}

    def open(self, kind: str, tool: str | None = None) -> str:
        if kind not in ATTEMPT_KINDS:
            raise ValueError("Unregistered attempt kind")
        attempt_id = self._new_id()
        self._records[attempt_id] = AttemptRecord(
            attempt_id=attempt_id, kind=kind, state="started", tool=tool,
            usage=unknown_usage(), started_at=self._clock(),
        )
        return attempt_id

    def complete(self, attempt_id: str, usage: UsageMeasurement | None = None) -> AttemptRecord:
        return self._close(attempt_id, "completed", usage)

    def fail(self, attempt_id: str, usage: UsageMeasurement | None = None) -> AttemptRecord:
        return self._close(attempt_id, "failed", usage)

    def cancel(self, attempt_id: str, usage: UsageMeasurement | None = None) -> AttemptRecord:
        """The operation was stopped and its cleanup ran to completion."""
        return self._close(attempt_id, "cancelled", usage)

    def _close(self, attempt_id: str, state: str, usage: UsageMeasurement | None) -> AttemptRecord:
        record = self._records[attempt_id]
        if record.state in TERMINAL_ATTEMPT_STATES:
            raise ValueError("Attempt is already closed")
        closed = replace(record, state=state, usage=usage or unknown_usage(),
                         finished_at=self._clock())
        self._records[attempt_id] = closed
        return closed

    def close_unfinished(self, state: str = "incomplete") -> AttemptSummary:
        """Label every attempt that never reached its own terminal record.

        ``cancelled`` means the cleanup ran. ``incomplete`` means nobody can say
        whether the work finished, so its usage stays unknown.
        """
        if state not in {"cancelled", "incomplete", "failed"}:
            raise ValueError("Unfinished attempts close as cancelled, incomplete or failed")
        now = self._clock()
        for attempt_id, record in list(self._records.items()):
            if record.state == "started":
                self._records[attempt_id] = replace(record, state=state, finished_at=now)
        return self.summary()

    def records(self) -> tuple[AttemptRecord, ...]:
        return tuple(self._records.values())

    def summary(self) -> AttemptSummary:
        return summarize_attempts(self._records.values())


def _setting(settings, name: str):
    value = getattr(settings, name, None)
    if isinstance(value, Path):
        return value.as_posix()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def config_snapshot(settings) -> tuple[dict, dict]:
    return (
        {name: _setting(settings, name) for name in INVARIANT_SETTINGS},
        {name: _setting(settings, name) for name in TREATMENT_SETTINGS},
    )


def config_fingerprints(settings) -> dict[str, str]:
    invariant, treatment = config_snapshot(settings)
    return {
        "invariant_config_fingerprint": fingerprint(invariant),
        "treatment_config_fingerprint": fingerprint(treatment),
    }
