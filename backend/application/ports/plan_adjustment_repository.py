"""Owner-scoped plan tasks: one version, one grant, at most two repair rounds.

The repository owns the atomic part. It never builds a model, never reads user
text and never decides whether a patch is sensible -- it stores what trusted
application code already decided and refuses to spend the same round twice.

Two orderings matter and are easy to get wrong:

* an idempotency receipt is matched **before** the version check, so a client
  retrying with the version it originally used gets its own answer back instead
  of a conflict it cannot resolve;
* a repair round is spent when it is **reserved**, before the next revision call,
  so a model that never produces a candidate cannot be retried for free.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

REPAIR_ROUND_LIMIT = 2

# collecting          -- the user is still stating what they want
# awaiting_scope_permission -- a domain grant is missing and must be asked for
# generating          -- a first candidate may be produced
# repairing           -- a candidate failed and a round was reserved
# awaiting_confirmation -- a passed candidate waits for the user
# awaiting_user_decision -- the task needs an answer it cannot infer
# activated / cancelled / expired -- terminal
TASK_STATES = frozenset({
    "collecting", "awaiting_scope_permission", "generating", "repairing",
    "awaiting_confirmation", "awaiting_user_decision", "activated",
    "cancelled", "expired",
})

TERMINAL_STATES = frozenset({"activated", "cancelled", "expired"})


@dataclass(frozen=True)
class TaskSnapshot:
    """The only persistent projection of a plan task.

    Every identifier is non-empty, every timestamp is timezone-aware UTC and the
    state is a closed enumeration: a snapshot that cannot be reasoned about is
    rejected at construction instead of propagating.
    """

    task_id: str
    version: int
    state: str
    base_plan_id: str
    base_head_revision: int
    read_domains: frozenset[str]
    change_domains: frozenset[str]
    constraint_digest: str
    candidate_id: str | None
    candidate_digest: str | None
    repair_rounds: int
    active_round_id: str | None
    operation_id: str | None
    expires_at: datetime
    candidate_expires_at: datetime | None

    def __post_init__(self) -> None:
        for name in ("task_id", "base_plan_id", "constraint_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"PLAN_TASK_FIELD_REQUIRED:{name}")
        for name in ("candidate_id", "candidate_digest", "active_round_id", "operation_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"PLAN_TASK_FIELD_INVALID:{name}")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("PLAN_TASK_FIELD_INVALID:version")
        if type(self.base_head_revision) is not int or self.base_head_revision < 1:
            raise ValueError("PLAN_TASK_FIELD_INVALID:base_head_revision")
        if type(self.repair_rounds) is not int or not 0 <= self.repair_rounds <= REPAIR_ROUND_LIMIT:
            raise ValueError("PLAN_TASK_FIELD_INVALID:repair_rounds")
        if self.state not in TASK_STATES:
            raise ValueError("PLAN_TASK_FIELD_INVALID:state")
        for name in ("read_domains", "change_domains"):
            value = getattr(self, name)
            if not isinstance(value, frozenset) or not value:
                raise ValueError(f"PLAN_TASK_FIELD_INVALID:{name}")
            if any(not isinstance(domain, str) or domain not in {"training", "diet"} for domain in value):
                raise ValueError(f"PLAN_TASK_FIELD_INVALID:{name}")
        if not self.change_domains <= self.read_domains:
            raise ValueError("PLAN_TASK_FIELD_INVALID:change_domains")
        _require_utc(self.expires_at, "expires_at")
        if self.candidate_expires_at is not None:
            _require_utc(self.candidate_expires_at, "candidate_expires_at")


def _require_utc(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(f"PLAN_TASK_FIELD_INVALID:{name}")


class PlanAdjustmentRepository(Protocol):
    def create_task(self, owner: str, *, base_plan_id: str, base_head_revision: int,
                    read_domains: frozenset[str], change_domains: frozenset[str],
                    constraints: dict, key: str) -> TaskSnapshot: ...

    def get(self, owner: str, task_id: str) -> TaskSnapshot: ...

    def grant(self, owner: str, task_id: str, expected_version: int,
              read_domains: frozenset[str], change_domains: frozenset[str], key: str) -> TaskSnapshot: ...

    def reserve_repair_round(self, owner: str, task_id: str, expected_version: int,
                             operation_id: str, failed_domains: frozenset[str]) -> TaskSnapshot: ...

    def submit_bundle(self, owner: str, task_id: str, expected_version: int,
                      operation_id: str, bundle, verdict) -> TaskSnapshot: ...

    def transition(self, owner: str, task_id: str, expected_version: int,
                   state: str, key: str) -> TaskSnapshot: ...

    def delete_user_data(self, owner: str) -> dict[str, int]: ...
