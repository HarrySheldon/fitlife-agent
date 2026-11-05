"""Plan adjustment as an application service: one task, one loop, one decision.

The service is where trusted application code stands between the user, the
repository and the model. It owns three things the model must never own:

* **the base plan and the head revision** -- read from the plan store, not from
  the request;
* **the hard constraints** -- snapshotted when the task is created, so a later
  profile edit cannot be validated against a plan the user never saw;
* **the confirmation** -- deliberately not implemented here. Task 6 adds the
  atomic activation; until then ``confirm`` refuses instead of writing a plan
  through a side door.

``execute`` runs the caller's runner exactly once. It does not create a second
runtime, a second task or a second budget: the task id is the budget scope, so
two rounds of one task share one ceiling.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Protocol

from backend.agent.plan_adjustment.session import PlanTaskSession
from backend.agent.plan_adjustment.validation import missing_constraint_paths
from backend.agent.safety import check_input
from backend.agent.tasks.contracts import task_error
from backend.application.ports.plan_adjustment_repository import (
    REPAIR_ROUND_LIMIT,
    REVIEW_CERTIFICATE_PREFIX,
    TERMINAL_STATES,
)
from backend.application.ports.task_budget_repository import TaskBudgetBinding
from backend.domain.errors import ApplicationError
from backend.domain.plan_adjustment import PlanConstraints
from backend.schemas import ValidationResult

DOMAINS = frozenset({"training", "diet"})
# States in which a model round may run. ``collecting`` and
# ``awaiting_scope_permission`` are waiting for the user, not for the model.
EXECUTABLE_STATES = frozenset({"generating", "repairing", "awaiting_user_decision"})
MAX_INSTRUCTIONS = 1000
# The constraints whose authority decides whether a candidate is *safe*, as
# opposed to whether it hits a target. Confirmation requires each one to be
# versioned: a safety check against a file cannot be reproduced at write time.
_HARD_CONSTRAINT_FIELDS = (
    "allergies_or_restrictions",
    "safety_conditions",
    "action_restrictions",
    "available_equipment",
    "session_minutes",
    "forbidden_exercises",
)


def _error(code: str, status: int = 409) -> ApplicationError:
    return ApplicationError(code=code, message=code, status_code=status, processing_mode="agent")


class PlanStore(Protocol):
    def get(self, user_id: str, plan_id: str): ...


@dataclass(frozen=True)
class RoundRequest:
    """What this round is being asked to do.

    The prose is *not* stored on the task. The task owns the decision state -- the
    grant, the frozen constraints, the rounds -- and the conversation owns the
    words. A round therefore carries the request it serves, so a repair after a
    failed candidate is asked about the same thing the first attempt was.
    """

    instructions: str


# ``runner(session, binding, request) -> AgentResult``: the composition root owns
# the runtime, gateway and tools. The service never constructs a model, and never
# builds a second runtime for a second round.
Runner = Callable[[PlanTaskSession, TaskBudgetBinding, RoundRequest], Awaitable[Any]]


def _grant(read_domains, change_domains) -> tuple[frozenset[str], frozenset[str]]:
    for name, value in (("read_domains", read_domains), ("change_domains", change_domains)):
        if not isinstance(value, frozenset) or not value:
            raise _error(f"PLAN_DOMAINS_INVALID:{name}", 422)
        if value - DOMAINS:
            raise _error(f"PLAN_DOMAINS_INVALID:{name}", 422)
    if not change_domains <= read_domains:
        raise _error("CHANGE_DOMAIN_NOT_READABLE", 422)
    return read_domains, change_domains


class PlanAdjustmentService:
    # ``call_limit`` is the ceiling for one task, not one run: three candidates
    # (the first plus two repairs) at the loop's twelve-decision bound. A task that
    # needs more has already failed to converge.
    def __init__(self, repository, plans: PlanStore, validation, *, constraints_source,
                 head_revision, runner: Runner, budgets, activations=None,
                 reviewer=None, call_limit: int = 36, token_limit: int = 512000,
                 review_required: bool = False, admission=None):
        self.repository = repository
        self.plans = plans
        self.validation = validation
        # ``constraints_source(owner) -> mapping``: the hard constraints a new
        # task is created against. Task 7 wires it to the versioned profile
        # targets; until then it is injected rather than guessed.
        self.constraints_source = constraints_source
        # ``head_revision(owner) -> int``: the authoritative head. Task 5 has no
        # head store yet, so it is injected rather than guessed from a file list.
        self.head_revision = head_revision
        self.runner = runner
        self.budgets = budgets
        # ``activations``: the store that can confirm atomically. Absent means the
        # deployment runs on a file store, which cannot, so ``confirm`` refuses.
        self.activations = activations
        self.reviewer = reviewer
        self.call_limit, self.token_limit = call_limit, token_limit
        # Whether the *current* safety policy wants a model review before a plan
        # becomes official. Read at confirmation time, not at task creation: the
        # policy can tighten while a candidate waits for the user.
        self.review_required = review_required
        # ``admission``: the account's single model slot. A plan round is a model
        # call, so it queues behind -- and is refused beside -- a coach turn. It is
        # optional only so the service can be exercised without one; every
        # deployment path passes it, and the HTTP tests prove the slot is held.
        self.admission = admission
        if call_limit < 1 or token_limit < 1:
            raise ValueError("PLAN_BUDGET_INVALID")

    # ---------------------------------------------------------------- entry

    def start(self, owner: str, base_plan_id: str, read_domains, change_domains,
              instructions: str, key: str) -> dict:
        """Create a task against the current head of an existing plan.

        ``instructions`` is validated but not stored: the conversation owns the
        prose, the task owns the decision state. Storing it twice would create a
        second copy of user text with a different retention rule.
        """
        _identity(owner, base_plan_id, key)
        read_domains, change_domains = _grant(read_domains, change_domains)
        if not isinstance(instructions, str) or not 1 <= len(instructions.strip()) <= MAX_INSTRUCTIONS:
            raise _error("INSTRUCTIONS_INVALID", 422)
        check_input(instructions)
        stored = self.plans.get(owner, base_plan_id)
        if stored is None:
            raise _error("PLAN_NOT_FOUND", 404)
        constraints = self._constraints(owner)
        revision = self.head_revision(owner)
        if type(revision) is not int or revision < 1:
            raise _error("PLAN_HEAD_UNAVAILABLE", 409)
        snapshot = self.repository.create_task(
            owner, base_plan_id=base_plan_id, base_head_revision=revision,
            read_domains=read_domains, change_domains=change_domains,
            constraints=constraints, key=key)
        if change_domains == read_domains and snapshot.state == "collecting":
            # Nothing is being withheld, so the task may generate. A task whose
            # change grant is narrower than its read grant stays in collecting:
            # that difference *is* the pending scope decision, and only ``grant``
            # resolves it.
            snapshot = self.repository.transition(
                owner, snapshot.task_id, snapshot.version, "generating",
                key=f"{key}:generate")
        return self._project(owner, snapshot)

    def get(self, owner: str, task_id: str) -> dict:
        """Read the task. Never starts a provider, never writes."""
        return self._project(owner, self._read(owner, task_id))

    def grant(self, owner: str, task_id: str, expected_version: int, read_domains,
              change_domains, decision: str, key: str) -> dict:
        _identity(owner, task_id, key)
        read_domains, change_domains = _grant(read_domains, change_domains)
        snapshot = self._read(owner, task_id)
        if decision == "allow":
            return self._project(owner, self.repository.grant(
                owner, task_id, expected_version, read_domains, change_domains, key))
        if decision != "deny":
            raise _error("PLAN_DECISION_INVALID", 422)
        # A denied grant does not close the task: it returns to collecting so the
        # user can ask for something narrower instead of losing the request.
        if snapshot.state == "awaiting_scope_permission":
            return self._project(owner, self.repository.transition(
                owner, task_id, expected_version, "collecting", key))
        return self._project(owner, snapshot)

    def answer(self, owner: str, task_id: str, expected_version: int,
               answers: Mapping[str, object], key: str) -> dict:
        """Fill the hard constraints the task reported as unknown."""
        _identity(owner, task_id, key)
        if not isinstance(answers, Mapping) or not answers:
            raise _error("PLAN_ANSWER_EMPTY", 422)
        # Validated against this task's frozen snapshot, not against a fresh read:
        # an answer fills a hole in what the task was created with.
        merged = dict(self.repository.constraints(owner, task_id))
        merged.update(dict(answers))
        try:
            PlanConstraints.model_validate(merged)
        except ValueError:
            raise _error("PLAN_ANSWER_NOT_ALLOWED", 422) from None
        return self._project(owner, self.repository.answer_constraints(
            owner, task_id, expected_version, answers, key))

    async def execute(self, owner: str, task_id: str, expected_version: int, key: str,
                      *, instructions: str | None = None, lease: str | None = None) -> dict:
        """Run one model round for this task, on this task's budget.

        The round takes the account's single slot. ``lease`` is how a caller that
        *already* holds it says so -- the coach, in the middle of a turn, deciding
        to hand work to a plan task. It is the turn id the caller holds, verified
        against the slot's own record; it is never a flag a request body can set,
        because "I am already admitted" is exactly the claim a second concurrent
        call would like to make for free.
        """
        _identity(owner, task_id, key)
        if not isinstance(instructions, str) or not 1 <= len(instructions.strip()) <= MAX_INSTRUCTIONS:
            raise _error("INSTRUCTIONS_INVALID", 422)
        check_input(instructions)
        snapshot = self._read(owner, task_id)
        replay = self.repository.claim_execution(owner, task_id, expected_version, key, instructions, reserve=False)
        if replay is not None:
            return {**replay, 'task': self._project(owner, snapshot), 'replayed': True}
        if snapshot.state in TERMINAL_STATES:
            raise task_error("STATE_TRANSITION")
        if snapshot.state not in EXECUTABLE_STATES and not (snapshot.state == 'awaiting_confirmation' and self.review_required):
            raise _error("SCOPE_GRANT_REQUIRED", 409)
        if snapshot.version != expected_version:
            raise task_error("TASK_VERSION_CONFLICT")
        if (snapshot.state == "repairing" and snapshot.repair_rounds >= REPAIR_ROUND_LIMIT
                and snapshot.active_round_id is None):
            # Both repairs are spent and the last candidate failed. Running
            # another round would spend a model call on a submission the store
            # must refuse, so the stop is written here instead of being merely
            # reported to a model that has nothing left to submit.
            stopped = self.repository.transition(
                owner, task_id, snapshot.version, "awaiting_user_decision",
                key=f"{task_id}:rounds-exhausted:{snapshot.version}")
            return {"task": self._project(owner, stopped), "answer": None, "receipt": None,
                    "answer_markdown": f"plan task {task_id}: {stopped.state}", "model": ""}
        request = RoundRequest(instructions=instructions)
        if self.admission is None:
            return await self._recorded_round(owner, task_id, request, key, expected_version)
        if lease is not None:
            held = self.admission.active(owner)
            if held is None or held.turn_id != lease:
                # The lease named a turn this account is not running. Running
                # anyway would be a second model call beside somebody's turn.
                raise _error("PLAN_EXECUTION_LEASE_INVALID", 409)
            return await self._recorded_round(owner, task_id, request, key, expected_version)
        return await self.admission.run_task(
            owner,
            question=f"Execute plan adjustment task {task_id}",
            action="plan_adjustment",
            surface="plan",
            produce=lambda: self._recorded_round(owner, task_id, request, key, expected_version),
        )

    async def _recorded_round(self, owner, task_id, request, key, expected_version):
        snapshot = self._read(owner, task_id)
        replay = self.repository.claim_execution(owner, task_id, expected_version, key, request.instructions)
        if replay is not None:
            return {**replay, 'task': self._project(owner, snapshot), 'replayed': True}
        result = await self._round(owner, task_id, request)
        # Store the bounded execution receipt, not another copy of the plan/diff.
        self.repository.finish_execution(owner, task_id, key,
            {name: result.get(name) for name in ('answer', 'receipt', 'answer_markdown', 'model')})
        return result

    async def _round(self, owner: str, task_id: str, request: RoundRequest) -> dict:
        # One budget per task, initialized once: a second round of the same task
        # continues the same ceiling instead of opening a fresh one.
        self.budgets.initialize(owner, task_id, self.call_limit, self.token_limit)
        binding = TaskBudgetBinding(self.budgets, owner, task_id)
        result = await self.runner(self.session(owner, task_id), binding, request)
        current = self._read(owner, task_id)
        return {"task": self._project(owner, current),
                "answer": getattr(result, "answer_markdown", getattr(result, "answer", None)),
                "receipt": getattr(result, "task_receipt", None),
                # What the slot publishes. A task round has no prose answer of its
                # own, so the record says what the task now is, not what a model
                # said about it.
                "answer_markdown": f"plan task {task_id}: {current.state}",
                "model": getattr(result, "model", "")}

    def confirm(self, owner: str, task_id: str, expected_version: int,
                expected_head_revision: int, candidate_digest: str, key: str) -> dict:
        """Write the candidate as an official plan, atomically.

        Everything that decides *whether* happens inside the store's transaction:
        the task's state and version, the head revision, the candidate digest and
        the grant. The re-validation happens there too, through ``_verify``, so
        the bytes checked are the bytes inserted. No model is constructed here --
        a confirmation that needed a provider call would be a confirmation that
        can fail after the user already agreed.
        """
        _identity(owner, task_id, key, candidate_digest)
        # Read first, so a task that belongs to somebody else is still "not found"
        # rather than an answer about how this deployment is configured.
        self._read(owner, task_id)
        if self.activations is None:
            # The refusal is the feature: a store without compare-and-swap cannot
            # tell two confirmations apart, so it must not accept one.
            raise _error("PLAN_CONFIRMATION_NOT_ENABLED", 409)
        receipt = self.activations.activate(
            owner,
            task_id=task_id,
            expected_version=expected_version,
            expected_head_revision=expected_head_revision,
            candidate_digest=candidate_digest,
            operation_key=key,
            verify=self._verify,
        )
        return {
            "task": self._project(owner, self._read(owner, task_id)),
            "plan": {
                "plan_id": receipt.plan_id,
                "head_revision": receipt.head_revision,
                "activated_at": receipt.activated_at.isoformat(),
                "kind": receipt.kind,
                "based_on_plan_id": receipt.based_on_plan_id,
            },
            "replayed": receipt.replayed,
        }

    def cancel(self, owner: str, task_id: str, expected_version: int, key: str) -> dict:
        _identity(owner, task_id, key)
        return self._project(owner, self.repository.transition(
            owner, task_id, expected_version, "cancelled", key))

    # ------------------------------------------------------------- internals

    def session(self, owner: str, task_id: str) -> PlanTaskSession:
        return PlanTaskSession(self.repository, owner, task_id, self.validation,
                               load_base=self._load_base, reviewer=self.reviewer)

    def _read(self, owner: str, task_id: str):
        try:
            return self.repository.get(owner, task_id)
        except KeyError:
            # A task that belongs to somebody else is indistinguishable from one
            # that does not exist.
            raise task_error("TASK_NOT_FOUND") from None

    def _load_base(self, owner: str, plan_id: str, revision: int) -> dict:
        stored = self.plans.get(owner, plan_id)
        if stored is None:
            raise _error("PLAN_NOT_FOUND", 404)
        return stored.plan.model_dump(mode="json")

    def _constraints(self, owner: str) -> dict:
        raw = self.constraints_source(owner)
        if not isinstance(raw, Mapping):
            raise _error("CONSTRAINT_SOURCE_INVALID", 409)
        try:
            return PlanConstraints.model_validate(dict(raw)).model_dump(mode="json")
        except ValueError:
            raise _error("CONSTRAINT_SOURCE_INVALID", 409) from None

    def _verify(self, context) -> dict:
        """Re-check the candidate inside the confirmation transaction.

        Runs on the bytes about to be inserted, against the task's own frozen
        constraints. Pure code: no gateway, no provider, no repository write.
        Returns the document to store, with its validation stamp, so the row and
        the verdict cannot describe different plans.
        """
        snapshot = context.constraints_at_write
        if snapshot is None:
            # No versioned store, so the safety check cannot be repeated at write
            # time. Approving on a check nobody can re-run is not a check.
            raise _error("CONSTRAINT_SOURCE_UNVERSIONED", 409)
        unversioned = _unversioned_hard_constraints(snapshot)
        if unversioned:
            # A file is still the authority for something that gates safety. The
            # remedy is to version that write path, not to approve.
            raise _error("CONSTRAINT_SOURCE_UNVERSIONED", 409)
        try:
            constraints = PlanConstraints.model_validate(dict(context.constraints))
        except ValueError:
            raise _error("CONSTRAINT_SOURCE_INVALID", 409) from None
        drift = _constraint_drift(dict(context.constraints), dict(snapshot.constraints))
        if drift:
            # The profile moved under a candidate that was reviewed against the
            # old values. Activating it would apply a decision to facts the user
            # never saw, so the task must be restarted instead.
            raise _error("CONSTRAINT_CHANGED", 409)
        if self.review_required and context.reviewed_digest != REVIEW_CERTIFICATE_PREFIX + context.candidate_digest:
            # Tightened while the candidate waited. Asking for the review here
            # would call a model inside the transaction, so the answer is "review
            # this again", not a silent approval.
            raise _error("CANDIDATE_REVIEW_REQUIRED", 409)
        document = dict(context.candidate_plan)
        base = (context.base_plan.plan.model_dump(mode="json")
                if context.base_plan is not None else None)
        violations = self.validation.review_document(document, constraints, base=base)
        if violations:
            raise _error("CANDIDATE_INVALID", 422)
        document["validation"] = ValidationResult(
            passed=True, warnings=[], violations=[], repair_suggestions=[],
        ).model_dump()
        return document

    def _project(self, owner: str, snapshot) -> dict:
        record = self.repository.latest_candidate(owner, snapshot.task_id)
        constraints = PlanConstraints.model_validate(self.repository.constraints(owner, snapshot.task_id))
        differences = []
        if record is not None and record.plan is not None:
            base = self._load_base(owner, snapshot.base_plan_id, snapshot.base_head_revision)
            from backend.domain.plan_diff import plan_differences
            differences = plan_differences(base, record.plan, snapshot.read_domains)
        return {
            "task_id": snapshot.task_id,
            "version": snapshot.version,
            "state": snapshot.state,
            "base_plan_id": snapshot.base_plan_id,
            "base_head_revision": snapshot.base_head_revision,
            "read_domains": sorted(snapshot.read_domains),
            "change_domains": sorted(snapshot.change_domains),
            "repair_rounds": snapshot.repair_rounds,
            "rounds_remaining": REPAIR_ROUND_LIMIT - snapshot.repair_rounds,
            "expires_at": snapshot.expires_at.isoformat(),
            "missing_constraints": missing_constraint_paths(constraints),
            "candidate": None if not snapshot.candidate_id else {
                "candidate_id": snapshot.candidate_id,
                "digest": snapshot.candidate_digest,
                "expires_at": (snapshot.candidate_expires_at.isoformat()
                               if snapshot.candidate_expires_at else None),
                "round": record.round_index if record else None,
                "diff": differences,
            },
            "failed_domains": sorted(record.failed_domains) if record else [],
            "violations": [dict(item) for item in record.violations] if record else [],
        }


def _identity(*values: str) -> None:
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise _error("PLAN_TASK_IDENTITY_REQUIRED", 422)


def _unversioned_hard_constraints(snapshot) -> list[str]:
    """Hard constraints whose authority the versioned store cannot name.

    Only a field the snapshot *claims* can be unversioned. A field missing from
    ``versions`` has no authority anywhere -- it can only come from the task's own
    clarification, and the task row is already its record -- so refusing on it
    would block confirmation for a check that has nothing to reproduce. A field
    present with ``None`` is the real case: the value exists, the store just cannot
    say which version of it the candidate was reviewed against.
    """
    return sorted(
        field for field in _HARD_CONSTRAINT_FIELDS
        if field in snapshot.versions and snapshot.versions[field] is None
    )


def _constraint_drift(snapshot: Mapping[str, object],
                      source: Mapping[str, object]) -> list[str]:
    """Fields the source now states differently from the task's snapshot.

    Not an equality test: a task that asked the user about an unknown field holds
    an answer the source never had, and comparing digests would refuse every
    answered task. A field the source does not state cannot contradict anything,
    so only stated-and-different counts as drift.
    """
    return sorted(
        key for key, value in source.items()
        if value is not None and snapshot.get(key) != value
    )
