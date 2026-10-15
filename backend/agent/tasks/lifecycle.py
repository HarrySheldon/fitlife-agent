"""Pure access and data classification contracts, without storage or retention policy.

S2/S3 owners must enforce these checks in their storage transactions and integrate
account deletion/export. These values do not implement those integrations, cleanup,
recovery, or an expiry default. A deleted snapshot cannot be exported or recovered
through this contract, even while physical cleanup is pending.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Callable, Literal

from backend.agent.tasks.contracts import TaskRef, _counter, _identifier, task_error


def _aware(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("An aware datetime is required")


@dataclass(frozen=True)
class BusinessDraft:
    task_id: str
    owner_id: str
    version: int
    validated_input: dict
    pending_questions: tuple[str, ...]
    candidate: dict | None
    counters: dict[str, int]
    dependencies: tuple[str, ...]
    run_links: tuple[str, ...]
    expires_at: datetime | None = None
    deleted: bool = False

    def __post_init__(self):
        TaskRef(self.task_id, self.version)
        _identifier(self.owner_id, "authenticated owner")
        if type(self.deleted) is not bool:
            raise ValueError("Invalid deletion state")
        if self.expires_at is not None:
            _aware(self.expires_at)
        for name in ("validated_input", "counters"):
            if not isinstance(getattr(self, name), dict):
                raise ValueError(f"Invalid {name}")
        if self.candidate is not None and not isinstance(self.candidate, dict):
            raise ValueError("Invalid candidate")
        for name, count in self.counters.items():
            _identifier(name, "counter")
            _counter(count, "counter")
        for name in ("pending_questions", "dependencies", "run_links"):
            values = getattr(self, name)
            if isinstance(values, str):
                raise ValueError(f"Invalid {name}")
            values = tuple(values)
            for value in values:
                _identifier(value, name)
            object.__setattr__(self, name, values)
        for name in ("validated_input", "candidate", "counters"):
            object.__setattr__(self, name, deepcopy(getattr(self, name)))


def require_access(resource: BusinessDraft | None, authenticated_owner: str, *,
                   clock: Callable[[], datetime], expected_version: int | None = None) -> BusinessDraft:
    """Authorize before exposing expiry/version; owners must apply atomically on write."""
    if not isinstance(authenticated_owner, str) or not authenticated_owner.strip():
        raise ValueError("AUTHENTICATED_OWNER_REQUIRED")
    if resource is None or resource.owner_id != authenticated_owner or resource.deleted:
        raise task_error("TASK_NOT_FOUND")
    now = clock()
    _aware(now)
    if resource.expires_at is not None and resource.expires_at <= now:
        raise task_error("TASK_EXPIRED")
    if expected_version is not None:
        _counter(expected_version, "expected version", 1)
        if resource.version != expected_version:
            raise task_error("TASK_VERSION_CONFLICT")
    return resource


def export_business_draft(resource: BusinessDraft | None, authenticated_owner: str, *,
                          clock: Callable[[], datetime], expected_version: int | None = None) -> dict:
    draft = require_access(resource, authenticated_owner, clock=clock, expected_version=expected_version)
    return deepcopy({
        "classification": "business_draft", "task_id": draft.task_id, "version": draft.version,
        "validated_input": draft.validated_input, "pending_questions": list(draft.pending_questions),
        "candidate": draft.candidate, "counters": draft.counters,
        "dependencies": list(draft.dependencies), "run_links": list(draft.run_links),
        "expires_at": draft.expires_at.isoformat() if draft.expires_at is not None else None,
    })


@dataclass(frozen=True)
class DiagnosticRecord:
    """Allowlisted metadata only; body, health text and reasoning have no field here.

    IDs must be generated opaque identifiers, never user-supplied text. Syntax
    validation bounds their representation; producers remain responsible for origin.
    """
    category: Literal["transition", "validation", "budget", "expiry", "deletion"]
    version: int
    count: int
    time: datetime
    task_id: str
    run_id: str

    def __post_init__(self):
        if self.category not in {"transition", "validation", "budget", "expiry", "deletion"}:
            raise ValueError("Invalid diagnostic category")
        _counter(self.version, "version", 1)
        _counter(self.count, "count")
        if self.version > 2**31 - 1 or self.count > 2**31 - 1:
            raise ValueError("Diagnostic number exceeds bound")
        _aware(self.time)
        for value in (self.task_id, self.run_id):
            if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value) is None:
                raise ValueError("Invalid opaque diagnostic identifier")

    def to_dict(self) -> dict:
        return {"classification": "diagnostic", "category": self.category, "version": self.version,
                "count": self.count, "time": self.time.isoformat(), "task_id": self.task_id, "run_id": self.run_id}
