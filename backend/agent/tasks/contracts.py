"""Pure task contracts. These helpers do not provide atomic storage operations."""
from __future__ import annotations
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.domain.errors import ApplicationError


def task_error(code: str) -> ApplicationError:
    """Stable public task errors; missing and foreign tasks share TASK_NOT_FOUND."""
    from backend.domain.errors import ApplicationError
    statuses = {"TASK_NOT_FOUND": 404, "TASK_VERSION_CONFLICT": 409,
                "IDEMPOTENCY_CONFLICT": 409, "TASK_EXPIRED": 410,
                "TASK_BUDGET_EXHAUSTED": 409, "REPAIR_LIMIT": 409}
    return ApplicationError(code=code, message=code, status_code=statuses[code], processing_mode="agent")


def _counter(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"Invalid {name}")


def _identifier(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid {name}")


@dataclass(frozen=True)
class TaskRef:
    task_id: str
    version: int

    def __post_init__(self):
        _identifier(self.task_id, "task_id")
        _counter(self.version, "version", 1)


def next_task_version(current: int, expected: int) -> int:
    """Validate a local optimistic version; the owner must compare-and-write atomically."""
    _counter(current, "version", 1)
    _counter(expected, "expected version", 1)
    if current != expected:
        raise task_error("TASK_VERSION_CONFLICT")
    return current + 1


def next_repair_round(current: int) -> int:
    """The caller supplies the task-wide count, never a per-domain count."""
    if type(current) is not int or current not in (0, 1):
        raise ValueError("REPAIR_LIMIT")
    return current + 1


@dataclass(frozen=True)
class RepairRound:
    round_id: str
    index: int
    pending_domains: frozenset[str]
    completed_domains: frozenset[str] = frozenset()

    def __post_init__(self):
        _identifier(self.round_id, "round_id")
        if type(self.index) is not int or self.index not in (1, 2):
            raise task_error("REPAIR_LIMIT")
        for name in ("pending_domains", "completed_domains"):
            values = getattr(self, name)
            if isinstance(values, str):
                raise ValueError("Domains must be a collection")
            try:
                values = tuple(values)
            except TypeError as error:
                raise ValueError("Domains must be a collection") from error
            for value in values:
                _identifier(value, "domain")
            values = frozenset(values)
            object.__setattr__(self, name, values)
        if self.pending_domains & self.completed_domains:
            raise ValueError("Pending and completed domains overlap")
        if not self.pending_domains and not self.completed_domains:
            raise ValueError("Repair round must contain domains")

    def complete(self, domain: str):
        if domain in self.completed_domains:
            return self
        if domain not in self.pending_domains:
            raise ValueError("Unknown repair domain")
        return replace(self, pending_domains=self.pending_domains - {domain},
                       completed_domains=self.completed_domains | {domain})


def start_repair_round(current: RepairRound | None, round_id: str, domains) -> RepairRound:
    """A repeated ID and original domain set replay unchanged, even after completion.

    Owners must retain prior rounds and claim IDs in their own transaction. This
    helper only compares the supplied round; it cannot detect older IDs or races.
    Run cancellation/timeouts have no effect on these independent task values.
    """
    if isinstance(domains, str):
        raise ValueError("Domains must be a collection")
    try:
        domains = tuple(domains)
    except TypeError as error:
        raise ValueError("Domains must be a collection") from error
    for domain in domains:
        _identifier(domain, "domain")
    domains = frozenset(domains)
    if not domains:
        raise ValueError("Repair round must contain domains")
    if current is not None and current.round_id == round_id:
        if domains != current.pending_domains | current.completed_domains:
            raise task_error("IDEMPOTENCY_CONFLICT")
        return current
    if current is not None and current.pending_domains:
        raise ValueError("Current repair round is unfinished")
    return RepairRound(round_id, next_repair_round(current.index if current else 0), domains)


@dataclass(frozen=True)
class TaskBudget:
    consumed_calls: int = 0
    reserved_calls: int = 0
    consumed_tokens: int = 0
    reserved_tokens: int = 0
    call_limit: int = 0
    token_limit: int = 0

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            _counter(getattr(self, name), name)
        if self.consumed_calls + self.reserved_calls > self.call_limit or self.consumed_tokens + self.reserved_tokens > self.token_limit:
            raise task_error("TASK_BUDGET_EXHAUSTED")

    def reserve(self, *, calls=0, tokens=0):
        """Pure proposal only: owner must reserve against persisted state atomically."""
        _counter(calls, "calls")
        _counter(tokens, "tokens")
        return replace(self, reserved_calls=self.reserved_calls + calls,
                       reserved_tokens=self.reserved_tokens + tokens)
