"""Plan-task session: the only place a candidate can come from.

The model may read the bound base plan and submit a bounded bundle. It cannot
create a task, widen a grant, choose a round, confirm a candidate or activate a
plan, because none of those exist as tools.

Three rules keep the repair loop honest.

**The round decides what may be touched.** A repair round is reserved with the
domains that failed, before the model is called; a bundle that reaches outside
that reservation is refused. A domain that already passed therefore cannot be
rewritten to make the other one fit.

**The base is what the user last saw validated.** A repair validates against the
previous candidate document, not against the original plan, so a partial fix is
not thrown away between rounds.

**Some failures are not repairable.** A missing hard constraint lives outside the
plan; asking the model to patch around it would spend a round to produce a
candidate that cannot pass. Those stop and ask the user instead.

Everything the receipt says is read back from the repository. A final answer that
claims a plan was changed is prose, and prose is not evidence.
"""
from __future__ import annotations

from typing import Any, Mapping

from backend.agent.plan_adjustment.validation import UNFIXABLE_CODES, candidate_plan
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
        # ``validation`` is the deterministic evaluator (Task 5). It is injected
        # so no always-passing stand-in can be wired into production by accident.
        self.validation = validation
        self.load_base = load_base
        # ``reviewer(candidate) -> code | None``. A code refuses the candidate for
        # the user to decide; an exception means the review did not happen, which
        # also publishes nothing.
        self.reviewer = reviewer
        self._verdict: CandidateVerdict | None = None
        self._round = 0
        self._review: str | None = None

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
        if snapshot.state == "awaiting_user_decision":
            # A persisted stop. The model may explain, but it has no round to spend.
            return SessionFrame(snapshot.version, "awaiting_user_decision",
                                {"reason": self._review or "USER_DECISION_REQUIRED",
                                 "round": snapshot.repair_rounds})
        if snapshot.state == "repairing" and snapshot.active_round_id is None:
            return self._reserve_repair(snapshot)
        return SessionFrame(snapshot.version, snapshot.state,
                            {"change_domains": sorted(snapshot.change_domains),
                             "round": snapshot.repair_rounds})

    def after_decision(self, decision) -> None:
        # Observation only. A decision never grants a domain or advances a round;
        # both happen in before_decision through the repository's compare-and-swap.
        return None

    def current(self):
        """The persisted state this session is bound to, for trusted callers.

        The runner needs the task version to open a run against the right task;
        it is read here rather than passed in so a caller cannot supply one.
        """
        return self._snapshot()

    def before_delivery(self, decision) -> Mapping[str, Any]:
        snapshot = self._snapshot()
        if snapshot.state != "awaiting_confirmation":
            # A candidate that was refused, unreviewed or still under repair is
            # not something the user can confirm, so it is not something the
            # answer may advertise.
            return {}
        if not snapshot.candidate_id or not snapshot.candidate_digest:
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
        base = self._working_base(snapshot)
        result: dict[str, Any] = {}
        if "meta" in requested:
            record = self.repository.latest_candidate(self.owner, self.task_id)
            result["meta"] = {"base_plan_id": snapshot.base_plan_id,
                              "base_head_revision": snapshot.base_head_revision,
                              "change_domains": sorted(snapshot.change_domains),
                              "working_round": record.round_index if record else None}
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
        base = self._working_base(snapshot)
        record = self.repository.latest_candidate(self.owner, self.task_id)
        # ``None`` means "no open round": the first candidate is not a repair and
        # may touch anything the grant covers.
        round_domains = self.repository.round_scope(self.owner, self.task_id)
        # Only the domains that already passed are frozen. The failing one is the
        # whole point of the round, so holding its digest would reject every fix.
        frozen = ({domain: record.domain_digests[domain] for domain in record.qualified_domains}
                  if (record is not None and round_domains is not None) else {})
        verdict = self.validation.evaluate(
            base, bundle, constraints, change_domains=snapshot.change_domains,
            round_domains=round_domains, frozen_digests=frozen)
        self._verdict = verdict
        self._review = None

        if verdict.violations and all(item.code in UNFIXABLE_CODES for item in verdict.violations):
            # A patch cannot supply a missing constraint or repair a legacy shape.
            # The submission is not recorded against the round slot: it is not an
            # attempt at the plan, and the retry after ``answer`` must be able to
            # use the round the task still has.
            self._review = "CONSTRAINT_REQUIRED"
            updated = self._stop(snapshot, "CONSTRAINT_REQUIRED")
            return self._submission(verdict, updated, candidate_id=None)

        candidate = candidate_plan(base, bundle, snapshot.change_domains)
        updated = self.repository.submit_bundle(
            self.owner, self.task_id, snapshot.version, self._operation_id(snapshot, verdict),
            bundle, verdict, candidate)
        self._round = updated.repair_rounds
        updated = self._dispose(updated, verdict, candidate)
        return self._submission(verdict, updated, candidate_id=verdict.candidate_id)

    # ----------------------------------------------------------- internals

    def _snapshot(self):
        return self.repository.get(self.owner, self.task_id)

    def _submission(self, verdict: CandidateVerdict, snapshot, *, candidate_id: str | None) -> dict:
        return {
            "candidate_id": candidate_id,
            "digest": verdict.digest,
            "passed": verdict.passed,
            "failed_domains": list(verdict.failed_domains),
            "violations": [item.model_dump() for item in verdict.violations],
            "domain_digests": dict(verdict.domain_digests),
            "task_version": snapshot.version,
            "state": snapshot.state,
            "round": snapshot.repair_rounds,
            "review": self._review,
        }

    def _working_base(self, snapshot) -> dict:
        """The plan this round edits: the last validated candidate, else the base."""
        record = self.repository.latest_candidate(self.owner, self.task_id)
        if record is not None and record.plan is not None:
            return dict(record.plan)
        return self.load_base(self.owner, snapshot.base_plan_id, snapshot.base_head_revision)

    def _operation_id(self, snapshot, verdict: CandidateVerdict) -> str:
        # The round is the idempotency scope: a retry inside one round returns
        # the same candidate, and a new round is a new operation.
        return f"{snapshot.task_id}:{snapshot.repair_rounds}:{verdict.digest[:16]}"

    def _dispose(self, snapshot, verdict: CandidateVerdict, candidate: dict | None):
        """Decide whether this candidate waits or is published.

        Called after the submission is durable, so a stop here never loses the
        record of what was produced and why it was not published.
        """
        if not verdict.passed:
            # A failed candidate stays in ``repairing``; the next decision reserves
            # the round. Nothing else to decide here.
            return snapshot
        code = self._review_candidate(candidate)
        if code is None:
            self._record_review(verdict.digest)
            return snapshot
        self._review = code
        return self._stop(snapshot, code)

    def _record_review(self, digest: str) -> None:
        """Note that a model review cleared this candidate, when the store can.

        Confirmation later asks "was *this* candidate reviewed under the current
        policy". Without a recorded digest the only honest answer is "unknown",
        which would refuse every confirmation once the policy tightens. A store
        without the column simply does not answer, and the refusal stays.
        """
        record = getattr(self.repository, "record_review", None)
        if record is not None and isinstance(digest, str) and digest:
            record(self.owner, self.task_id, digest)

    def _review_candidate(self, candidate: dict | None) -> str | None:
        if self.reviewer is None or candidate is None:
            return None
        try:
            code = self.reviewer(candidate)
        except Exception:
            # A review that did not happen is not a review that passed.
            return "CANDIDATE_REVIEW_UNAVAILABLE"
        return str(code)[:64] if code else None

    def _stop(self, snapshot, code: str):
        if snapshot.state == "awaiting_user_decision":
            # Already stopped: asking again must not turn a stop into a conflict.
            return snapshot
        return self.repository.transition(
            self.owner, self.task_id, snapshot.version, "awaiting_user_decision",
            key=f"{snapshot.task_id}:stop:{snapshot.version}:{code}")

    def _reserve_repair(self, snapshot) -> SessionFrame:
        if snapshot.repair_rounds >= REPAIR_ROUND_LIMIT:
            # Out of rounds: stop spending model calls and hand the decision back
            # to the user instead of looping.
            return SessionFrame(snapshot.version, "awaiting_user_decision",
                                {"reason": "REPAIR_LIMIT", "round": snapshot.repair_rounds})
        failed, violations = self._failed_domains(snapshot)
        if not failed:
            return SessionFrame(snapshot.version, "awaiting_user_decision",
                                {"reason": "NOTHING_TO_REPAIR", "round": snapshot.repair_rounds})
        reserved = self.repository.reserve_repair_round(
            self.owner, self.task_id, snapshot.version,
            f"{snapshot.task_id}:reserve:{snapshot.repair_rounds + 1}", failed)
        self._round = reserved.repair_rounds
        return SessionFrame(reserved.version, "repairing", {
            "round": reserved.repair_rounds,
            "failed_domains": sorted(failed),
            "violations": violations,
        })

    def _failed_domains(self, snapshot) -> tuple[frozenset[str], list[dict]]:
        """What to repair, from memory when this process produced it, else from storage."""
        if self._verdict is not None:
            return (frozenset(self._verdict.failed_domains),
                    [item.model_dump() for item in self._verdict.violations])
        record = self.repository.latest_candidate(self.owner, self.task_id)
        if record is not None and record.failed_domains:
            return frozenset(record.failed_domains), []
        return frozenset(), []
