"""Plan-task session: the only place a candidate can come from.

The model may read the bound base plan and submit a bounded bundle. It cannot
create a task, widen a grant, choose a round, confirm a candidate or activate a
plan, because none of those exist as tools.

Everything the receipt says is read back from the repository. A final answer that
claims a plan was changed is prose, and prose is not evidence.
"""
from __future__ import annotations

from typing import Any, Mapping

from backend.agent.task_session import SessionFrame
from backend.application.ports.plan_adjustment_repository import (
    REPAIR_ROUND_LIMIT,
    TERMINAL_STATES,
)
from backend.domain.plan_adjustment import CandidateBundle, CandidateVerdict, PlanConstraints

READ_FIELDS = frozenset({"meta", "constraints", "training", "diet"})
DOMAIN_FIELDS = {"training": "workout_plan", "diet": "diet_plan"}


def _iso(value) -> str:
    return value.isoformat() if value is not None else ""


class PlanTaskSession:
    def __init__(self, repository, owner: str, task_id: str, validation, *,
                 load_base, reviewer=None):
        self.repository = repository
        self.owner, self.task_id = owner, task_id
        # ``validation`` is the deterministic evaluator (Task 5). Task 4 wires
        # the seam and keeps production behind the feature switch until that
        # evaluator exists.
        self.validation = validation
        self.load_base = load_base
        self.reviewer = reviewer
        self._verdict: CandidateVerdict | None = None
        self._round = 0

    # ------------------------------------------------------------- protocol

    def before_decision(self) -> SessionFrame:
        snapshot = self._snapshot()
        if snapshot.state == "expired":
            raise PermissionError("TASK_EXPIRED")
        if snapshot.state in TERMINAL_STATES:
            raise PermissionError("TASK_CLOSED")
        if snapshot.state == "awaiting_confirmation":
            return SessionFrame(snapshot.version, "awaiting_confirmation",
                                {"candidate_id": snapshot.candidate_id or ""})
        if snapshot.state == "repairing" and snapshot.active_round_id is None:
            return self._reserve_repair(snapshot)
        return SessionFrame(snapshot.version, snapshot.state,
                            {"change_domains": sorted(snapshot.change_domains),
                             "round": snapshot.repair_rounds})

    def after_decision(self, decision) -> None:
        # Observation only. A decision never grants a domain or advances a round;
        # both happen in before_decision through the repository's compare-and-swap.
        return None

    def before_delivery(self, decision) -> Mapping[str, Any]:
        snapshot = self._snapshot()
        if not snapshot.candidate_id or not snapshot.candidate_digest:
            # No candidate means no receipt. The final text cannot supply one.
            return {}
        return {
            "task_id": snapshot.task_id,
            "version": snapshot.version,
            "state": snapshot.state,
            "candidate_id": snapshot.candidate_id,
            "candidate_digest": snapshot.candidate_digest,
            "candidate_expires_at": _iso(snapshot.candidate_expires_at),
            "base_head_revision": snapshot.base_head_revision,
        }

    # -------------------------------------------------------------- tools

    def read_base(self, fields) -> dict:
        snapshot = self._snapshot()
        requested = set(fields)
        unknown = requested - READ_FIELDS
        if unknown:
            raise PermissionError("FIELD_NOT_AUTHORIZED")
        base = self._base(snapshot)
        result: dict[str, Any] = {}
        if "meta" in requested:
            result["meta"] = {"base_plan_id": snapshot.base_plan_id,
                              "base_head_revision": snapshot.base_head_revision,
                              "change_domains": sorted(snapshot.change_domains)}
        if "constraints" in requested:
            result["constraints"] = self.repository.constraints(self.owner, self.task_id)
        for domain, key in DOMAIN_FIELDS.items():
            if domain not in requested:
                continue
            if domain not in snapshot.read_domains:
                # A training-only task does not get to see the diet plan, even
                # to reason about it.
                raise PermissionError("FIELD_NOT_AUTHORIZED")
            result[domain] = base.get(key, {})
        return result

    def submit_candidate(self, patches) -> dict:
        snapshot = self._snapshot()
        bundle = CandidateBundle(patches=tuple(patches))
        constraints = PlanConstraints.model_validate(
            self.repository.constraints(self.owner, self.task_id))
        verdict = self.validation.evaluate(self._base(snapshot), bundle, constraints)
        updated = self.repository.submit_bundle(
            self.owner, self.task_id, snapshot.version, self._operation_id(snapshot, verdict),
            bundle, verdict)
        self._verdict = verdict
        self._round = updated.repair_rounds
        return {
            "candidate_id": verdict.candidate_id,
            "digest": verdict.digest,
            "passed": verdict.passed,
            "failed_domains": list(verdict.failed_domains),
            "violations": [item.model_dump() for item in verdict.violations],
            "task_version": updated.version,
            "state": updated.state,
            "round": updated.repair_rounds,
        }

    # ----------------------------------------------------------- internals

    def _snapshot(self):
        return self.repository.get(self.owner, self.task_id)

    def _base(self, snapshot) -> dict:
        return self.load_base(self.owner, snapshot.base_plan_id, snapshot.base_head_revision)

    def _operation_id(self, snapshot, verdict: CandidateVerdict) -> str:
        # The round is the idempotency scope: a retry inside one round returns
        # the same candidate, and a new round is a new operation.
        return f"{snapshot.task_id}:{snapshot.repair_rounds}:{verdict.digest[:16]}"

    def _reserve_repair(self, snapshot) -> SessionFrame:
        if snapshot.repair_rounds >= REPAIR_ROUND_LIMIT:
            # Out of rounds: stop spending model calls and hand the decision back
            # to the user instead of looping.
            return SessionFrame(snapshot.version, "awaiting_user_decision",
                                {"reason": "REPAIR_LIMIT", "round": snapshot.repair_rounds})
        failed = frozenset(self._verdict.failed_domains) if self._verdict else snapshot.change_domains
        reserved = self.repository.reserve_repair_round(
            self.owner, self.task_id, snapshot.version,
            f"{snapshot.task_id}:reserve:{snapshot.repair_rounds + 1}", failed)
        self._round = reserved.repair_rounds
        return SessionFrame(reserved.version, "repairing", {
            "round": reserved.repair_rounds,
            "failed_domains": sorted(failed),
            "violations": [item.model_dump() for item in (self._verdict.violations if self._verdict else ())],
        })

