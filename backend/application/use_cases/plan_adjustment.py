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

from typing import Any, Awaitable, Callable, Mapping, Protocol

from backend.agent.plan_adjustment.session import PlanTaskSession
from backend.agent.plan_adjustment.validation import missing_constraint_paths
from backend.agent.safety import check_input
from backend.agent.tasks.contracts import task_error
from backend.application.ports.plan_adjustment_repository import (
    REPAIR_ROUND_LIMIT,
    TERMINAL_STATES,
)
from backend.application.ports.task_budget_repository import TaskBudgetBinding
from backend.domain.errors import ApplicationError
from backend.domain.plan_adjustment import PlanConstraints

DOMAINS = frozenset({"training", "diet"})
# States in which a model round may run. ``collecting`` and
# ``awaiting_scope_permission`` are waiting for the user, not for the model.
EXECUTABLE_STATES = frozenset({"generating", "repairing", "awaiting_user_decision"})
MAX_INSTRUCTIONS = 1000


def _error(code: str, status: int = 409) -> ApplicationError:
    return ApplicationError(code=code, message=code, status_code=status, processing_mode="agent")


class PlanStore(Protocol):
    def get(self, user_id: str, plan_id: str): ...


# ``runner(session, binding) -> AgentResult``: the composition root owns the
# runtime, gateway and tools. The service never constructs a model, and never
# builds a second runtime for a second round.
Runner = Callable[[PlanTaskSession, TaskBudgetBinding], Awaitable[Any]]


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
                 head_revision, runner: Runner, budgets,
                 reviewer=None, call_limit: int = 36, token_limit: int = 512000):
        self.repository = repository
        self.plans = plans
        self.validation = validation
        # ``constraints_source(owner) -> mapping``: the trusted hard-constraint
        # snapshot. Task 7 wires it to the versioned profile targets.
        self.constraints_source = constraints_source
        # ``head_revision(owner) -> int``: the authoritative head. Task 5 has no
        # head store yet, so it is injected rather than guessed from a file list.
        self.head_revision = head_revision
        self.runner = runner
        self.budgets = budgets
        self.reviewer = reviewer
        self.call_limit, self.token_limit = call_limit, token_limit
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

    async def execute(self, owner: str, task_id: str, expected_version: int, key: str) -> dict:
        """Run one model round for this task, on this task's budget."""
        _identity(owner, task_id, key)
        snapshot = self._read(owner, task_id)
        if snapshot.state in TERMINAL_STATES:
            raise task_error("STATE_TRANSITION")
        if snapshot.state not in EXECUTABLE_STATES:
            raise _error("SCOPE_GRANT_REQUIRED", 409)
        if snapshot.version != expected_version:
            raise task_error("TASK_VERSION_CONFLICT")
        # One budget per task, initialized once: a second round of the same task
        # continues the same ceiling instead of opening a fresh one.
        self.budgets.initialize(owner, task_id, self.call_limit, self.token_limit)
        binding = TaskBudgetBinding(self.budgets, owner, task_id)
        result = await self.runner(self.session(owner, task_id), binding)
        current = self._read(owner, task_id)
        return {"task": self._project(owner, current),
                "answer": getattr(result, "answer", None),
                "receipt": getattr(result, "task_receipt", None)}

    def confirm(self, owner: str, task_id: str, expected_version: int,
                expected_head_revision: int, candidate_digest: str, key: str) -> dict:
        """Refuse until Task 6 provides the atomic activation.

        The refusal is the feature: a confirmation that wrote a plan through any
        other path would be an activation nobody versioned. ``expected_version``,
        ``expected_head_revision`` and ``candidate_digest`` are accepted so the
        signature does not change when the transaction arrives; none of them is
        used to decide anything yet.
        """
        _identity(owner, task_id, key)
        self._read(owner, task_id)
        raise _error("PLAN_CONFIRMATION_NOT_ENABLED", 409)

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

    def _project(self, owner: str, snapshot) -> dict:
        record = self.repository.latest_candidate(owner, snapshot.task_id)
        constraints = PlanConstraints.model_validate(self.repository.constraints(owner, snapshot.task_id))
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
            },
            "failed_domains": sorted(record.failed_domains) if record else [],
            "violations": [dict(item) for item in record.violations] if record else [],
        }


def _identity(*values: str) -> None:
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise _error("PLAN_TASK_IDENTITY_REQUIRED", 422)
