"""The plan store: history, the single head, and the confirmation contract.

Three things are deliberately kept apart here.

**History** is immutable. A plan id names one document forever, so a second write
with the same id and different bytes is a conflict rather than an update -- the
whole point of keeping history is that yesterday's answer still exists.

**The head** is one row per owner. It carries a revision because a confirmation
compares that revision and writes ``revision + 1``: two confirmations of the same
base cannot both win, and the loser is told the base moved instead of silently
replacing the winner.

**The legacy head rule** lives in ``legacy_head`` and nowhere else. The file
reader and the importer both use it, so a data directory reads the same before
and after a migration instead of shifting its head by one because two copies of
"latest activated_at, then plan id" disagreed about ties.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict

from backend.application.ports.profile_target_repository import ConstraintSnapshot
from backend.schemas import GeneratedPlan


PlanKind = Literal["deterministic", "agent_adjusted"]


class StoredPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    plan_id: str
    activated_at: AwareDatetime
    kind: PlanKind
    based_on_plan_id: str | None = None
    plan: GeneratedPlan


class StoredPlanDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    draft_id: str
    created_at: AwareDatetime
    kind: PlanKind
    based_on_plan_id: str | None = None
    plan: GeneratedPlan


class PlanHead(BaseModel):
    """The plan a new task must be based on, plus the revision that pins it.

    ``revision`` counts activations for one owner, not versions of one plan. It is
    the compare-and-swap token: it only ever grows, so a confirmation holding an
    older value loses. ``plan_id`` is carried alongside because the revision alone
    cannot say *which* plan the counter reached.
    """

    model_config = ConfigDict(frozen=True)

    plan_id: str
    revision: int
    updated_at: AwareDatetime


class PlanActivationReceipt(BaseModel):
    """What a confirmation wrote, replayed verbatim for a repeated request."""

    model_config = ConfigDict(frozen=True)

    plan_id: str
    head_revision: int
    activated_at: AwareDatetime
    kind: PlanKind
    based_on_plan_id: str | None = None
    replayed: bool = False


@dataclass(frozen=True)
class ActivationContext:
    """Everything the confirmation read inside its own transaction.

    The verifier receives this instead of re-reading: a check performed against a
    snapshot taken before ``BEGIN IMMEDIATE`` would be a check of different bytes
    than the ones about to be inserted.
    """

    user_id: str
    task_id: str
    base_plan_id: str
    base_head_revision: int
    constraints: dict[str, Any]
    reviewed_digest: str | None
    candidate_id: str
    candidate_digest: str
    candidate_plan: dict[str, Any]
    head: PlanHead | None
    base_plan: StoredPlan | None
    # The versioned constraint snapshot read on this transaction's own
    # connection, or ``None`` when the deployment has no such store. ``None`` is
    # not "unchanged": it means the check cannot be reproduced at write time.
    constraints_at_write: ConstraintSnapshot | None = None


# ``verify(context)`` raises to refuse and returns the document to store. It must
# be pure code: the confirmation transaction never constructs or calls a model, so
# a refusal it cannot compute is a refusal it must report rather than resolve. The
# return value is the *verified* document, not the candidate: what gets inserted
# is what the last check saw, never a document the check never ran against.
Verifier = Callable[[ActivationContext], dict[str, Any]]


def legacy_head(plans: Sequence[StoredPlan]) -> PlanHead | None:
    """The head a data directory had before heads existed.

    Latest ``activated_at`` wins; equal timestamps fall back to the plan id so the
    answer does not depend on directory order. The revision is the number of
    plans, which makes it the same counter a sequence of activations would have
    produced -- so a task started before a migration is not told its base is stale
    merely because the storage moved.
    """
    if not plans:
        return None
    ordered = sorted(plans, key=lambda item: (item.activated_at, item.plan_id))
    newest = ordered[-1]
    return PlanHead(
        plan_id=newest.plan_id,
        revision=len(ordered),
        updated_at=newest.activated_at,
    )


class PlanRepository(Protocol):
    def save(self, user_id: str, plan: StoredPlan) -> None: ...

    def list(self, user_id: str) -> list[StoredPlan]: ...

    def get(self, user_id: str, plan_id: str) -> StoredPlan | None: ...

    def save_draft(self, user_id: str, draft: StoredPlanDraft) -> None: ...

    def get_draft(self, user_id: str, draft_id: str) -> StoredPlanDraft | None: ...

    def take_draft(self, user_id: str, draft_id: str) -> StoredPlanDraft | None: ...

    def current_head(self, user_id: str) -> PlanHead | None: ...


class PlanActivationRepository(Protocol):
    """The half of the store that can confirm a candidate atomically.

    Only a versioned store implements this. A file store has no compare-and-swap,
    so it must not pretend: the absence of the method is how the service knows
    confirmation is unavailable rather than merely unimplemented.
    """

    def activate(
        self,
        user_id: str,
        *,
        task_id: str,
        expected_version: int,
        expected_head_revision: int,
        candidate_digest: str,
        operation_key: str,
        verify: Verifier,
    ) -> PlanActivationReceipt: ...
