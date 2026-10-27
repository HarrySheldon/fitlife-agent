"""The seam between a coach turn and a plan task.

A coach turn may hand work to a plan task. That is the only way two model calls
for one account could end up running at once, so the handoff is the interesting
part: the task must join the slot the coach already holds rather than asking for a
second one, and it must refuse a lease it cannot verify.

The last case here is the one that is easy to get wrong and hard to notice: a user
who cancels while the model is still deciding. The decision then arrives for a
turn that no longer exists, and the candidate it describes must never be written.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import asyncio

import pytest

from backend.agent.decision import FinalDecision, ToolCall
from backend.application.ports.agent_decision_gateway import AgentDecisionResult
from backend.api.coach_conversations import (
    get_coach_admission_service,
    reset_coach_turn_services,
)
from backend.api.plan_adjustment import reset_plan_adjustment_services
from backend.application.use_cases.plan_adjustment import PlanAdjustmentService
from backend.config import get_settings
from backend.domain.errors import ApplicationError
from backend.infrastructure.sqlite.runtime import initialize_database
from backend.tests.test_plan_adjustment_api import (
    INSTRUCTIONS,
    _service,
)
from backend.tests.test_plan_adjustment_service import ROUND_0, ROUND_0_PATCHES


@pytest.fixture(autouse=True)
def reset_caches():
    yield
    reset_plan_adjustment_services()
    reset_coach_turn_services()
    get_settings.cache_clear()


@pytest.fixture
def owner(monkeypatch):
    data_dir = Path(".tmp") / "pytest-plan-adjustment-handoff" / uuid4().hex
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("PLAN_ADJUSTMENT_TASKS_ENABLED", "true")
    get_settings.cache_clear()
    initialize_database()
    return "handoff-user"


def _started(service: PlanAdjustmentService, owner: str) -> dict:
    return service.start(owner, "plan-aaaaaaaa", frozenset({"training", "diet"}),
                         frozenset({"training", "diet"}), INSTRUCTIONS, key="create-1")


def test_a_held_turn_lets_the_task_run_without_a_second_slot(owner):
    """The coach already owns the account's slot, so the task must not ask again.

    If ``execute`` tried to take the slot it would be refused by the very turn
    that handed it the work -- the deadlock the lease exists to avoid.
    """
    admission = get_coach_admission_service()
    service = _service(owner, scripts=[ROUND_0], admission=admission)
    task = _started(service, owner)
    held = admission.begin_legacy(
        owner, question="帮我调整一下计划", action="adjust_next_plan", surface="plan")

    try:
        result = asyncio.run(service.execute(
            owner, task["task_id"], task["version"], "exec-1",
            instructions=INSTRUCTIONS, lease=held.turn_id))
    finally:
        admission.fail_legacy(owner, held, error_code="TEST_RELEASED")

    # The round ran, and the turn that lent the slot is still the active one.
    assert result["task"]["version"] > task["version"]
    assert result["task"]["failed_domains"] == ["diet", "training"]


def test_a_lease_the_account_is_not_holding_is_refused(owner):
    """A lease is a turn id the slot itself confirms, not a claim in a body."""
    admission = get_coach_admission_service()
    service = _service(owner, scripts=[ROUND_0], admission=admission)
    task = _started(service, owner)

    with pytest.raises(ApplicationError, match="PLAN_EXECUTION_LEASE_INVALID"):
        asyncio.run(service.execute(
            owner, task["task_id"], task["version"], "exec-1",
            instructions=INSTRUCTIONS, lease="a-turn-that-does-not-exist"))


def test_another_accounts_turn_is_not_a_lease(owner):
    """A turn id from somebody else must not unlock this account's slot."""
    admission = get_coach_admission_service()
    service = _service(owner, scripts=[ROUND_0], admission=admission)
    task = _started(service, owner)
    other = admission.begin_legacy(
        "a-different-account", question="解释训练", action="explain_today", surface="today")

    try:
        with pytest.raises(ApplicationError, match="PLAN_EXECUTION_LEASE_INVALID"):
            asyncio.run(service.execute(
                owner, task["task_id"], task["version"], "exec-1",
                instructions=INSTRUCTIONS, lease=other.turn_id))
    finally:
        admission.fail_legacy("a-different-account", other, error_code="TEST_RELEASED")


class _CancellingGateway:
    """A model that thinks while the user cancels, then answers anyway.

    The answer describes a candidate the user is no longer waiting for. It must
    never reach the store: the write is refused by the runtime before the tool
    runs, which is why this test asserts on the *task*, not on an exception.
    """

    model = "offline"

    def __init__(self, admission, owner: str, decisions) -> None:
        self.admission = admission
        self.owner = owner
        self.decisions = iter(decisions)
        self.cancelled = False

    def decide(self, request):
        active = self.admission.active(self.owner)
        if active is not None:
            self.admission.cancel(self.owner, active.turn_id)
            self.cancelled = True
        return AgentDecisionResult(next(self.decisions), self.model, {"total_tokens": 10})


def test_a_cancelled_turn_cannot_publish_a_candidate(owner):
    """The late answer is dropped rather than written into the task."""
    from backend.tests.test_plan_adjustment_api import _executor

    admission = get_coach_admission_service()
    service = _service(owner, scripts=[], admission=admission)
    task = _started(service, owner)
    gateway = _CancellingGateway(admission, owner, [
        # A real bundle, not an empty one: an empty bundle is refused by the tool
        # schema, which would let this test pass without the cancellation working.
        ToolCall(call_id="c0", tool="plan.submit_candidate",
                 arguments={"patches": ROUND_0_PATCHES}),
        FinalDecision(body="已经调整好了。"),
    ])

    async def run(session, binding, request):
        from backend.agent.contracts import AgentCommand
        from backend.agent.runtime import AgentRuntime
        from backend.agent.tasks.contracts import TaskRef
        from backend.agent.unified_coach import UnifiedCoachWorkflow

        runtime = AgentRuntime(task_budget_binding_factory=lambda user, ref: binding)
        command = AgentCommand("plan_adjustment", request.instructions, owner,
                               surface="plan", language="zh-CN",
                               task_ref=TaskRef(binding.task_id, session.current().version))
        return await runtime.execute(command, UnifiedCoachWorkflow(
            gateway, _executor(session, owner), session=session))

    service.runner = run

    with pytest.raises(Exception):
        asyncio.run(service.execute(
            owner, task["task_id"], task["version"], "exec-1",
            instructions=INSTRUCTIONS))

    assert gateway.cancelled is True
    after = service.get(owner, task["task_id"])
    # Nothing was written: no candidate, and the task is where it was.
    assert after["candidate"] is None
    assert after["state"] == task["state"]
    assert after["version"] == task["version"]
