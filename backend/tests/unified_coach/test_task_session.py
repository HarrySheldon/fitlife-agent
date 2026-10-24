"""The loop drives tools through their spec, and a session is only an observer.

The first test is the important one: a tool that exists only in the test file is
executed by the unchanged decision loop. If adding it had required an edit to the
loop, this file could not exist.
"""
import asyncio

import pytest
from pydantic import BaseModel, ConfigDict

from backend.agent.context_builder import ExecutionPrincipal
from backend.agent.contracts import AgentCommand
from backend.agent.decision import FinalDecision, ToolCall
from backend.agent.runtime import AgentRuntime
from backend.agent.skills.catalog import SkillCatalog
from backend.agent.task_session import AdviceSession, SessionFrame
from backend.agent.tools.executor import ToolExecutor
from backend.agent.tools.handlers import BoundFitnessReads
from backend.agent.tools.spec import ToolSpec
from backend.agent.unified_coach import UnifiedCoachWorkflow
from backend.application.ports.agent_decision_gateway import AgentDecisionResult


class EchoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


class ForbiddenRepository:
    def read_profile(self, owner):
        raise AssertionError("Private data was read")

    read_workouts = read_profile
    read_meals = read_profile


class ScriptedGateway:
    model = "offline"

    def __init__(self, decisions):
        self.decisions = iter(decisions)
        self.requests = []

    def decide(self, request):
        self.requests.append(request)
        return AgentDecisionResult(next(self.decisions), self.model, {"total_tokens": 10})


def _executor(specs):
    principal = ExecutionPrincipal("owner", authorized_domains=frozenset({"profile", "training"}))
    return ToolExecutor(principal=principal, reads=BoundFitnessReads(ForbiddenRepository(), "owner"),
                        catalog=SkillCatalog(), authorize=lambda p: p.authorized_domains,
                        retriever=lambda *a, **k: [], language="zh-CN", specs=specs)


def _run(decisions, specs=None, session=None):
    executor = _executor(specs)
    gateway = ScriptedGateway(decisions)
    command = AgentCommand("chat", "教练你好，我需要今天练胸，给出一份完整的训练计划", "owner", language="zh-CN")
    result = asyncio.run(AgentRuntime().execute(
        command, UnifiedCoachWorkflow(gateway, executor, session=session)))
    return result, gateway, executor


def test_a_test_only_tool_runs_without_editing_the_loop():
    seen = []

    def handler(args, ctx):
        seen.append(args.text)
        return {"echo": args.text}

    spec = ToolSpec(name="test.echo", args_model=EchoArgs, effect="private_read", handler=handler)
    result, gateway, _ = _run([
        ToolCall(call_id="a", tool="test.echo", arguments={"text": "hi"}),
        FinalDecision(body="按计划执行，注意身体反馈。"),
    ], specs={"test.echo": spec})

    assert seen == ["hi"]
    assert result.trace["decision_count"] == 2
    assert len(gateway.requests) == 2


def test_a_public_tool_result_is_not_treated_as_private():
    spec = ToolSpec(name="test.echo", args_model=EchoArgs, effect="public_read",
                    handler=lambda args, ctx: {"echo": args.text})
    _, _, executor = _run([
        ToolCall(call_id="a", tool="test.echo", arguments={"text": "hi"}),
        FinalDecision(body="按计划执行，注意身体反馈。"),
    ], specs={"test.echo": spec})

    assert executor.observations["a"]["public"] is True


def test_advice_session_has_no_task_side_effects():
    session = AdviceSession()
    assert session.before_decision() == SessionFrame(revision=0, phase="advice", state={})
    assert session.after_decision(FinalDecision(body="建议")) is None
    assert session.before_delivery(FinalDecision(body="建议")) == {}


def test_plain_advice_keeps_its_previous_trace():
    result, _, _ = _run([FinalDecision(body="按计划执行，注意身体反馈。")])

    assert "task_receipt" not in result.trace
    assert result.trace["agent_mode"] == "unified"


def test_a_session_receipt_is_attached_to_the_result():
    class Recording(AdviceSession):
        def before_delivery(self, decision):
            return {"task_id": "t1", "state": "awaiting_confirmation"}

    result, _, _ = _run([FinalDecision(body="按计划执行，注意身体反馈。")], session=Recording())

    assert result.trace["task_receipt"] == {"task_id": "t1", "state": "awaiting_confirmation"}


def test_a_session_only_observes_validated_decisions():
    seen = []

    class Recording(AdviceSession):
        def after_decision(self, decision):
            seen.append(decision)

    _run([
        ToolCall(call_id="a", tool="skills.search", arguments={"query": "训练"}),
        FinalDecision(body="按计划执行，注意身体反馈。"),
    ], session=Recording())

    assert [type(decision).__name__ for decision in seen] == ["ToolCall", "FinalDecision"]


def test_before_decision_runs_at_loop_entry_and_again_before_the_gateway():
    class Counting(AdviceSession):
        def __init__(self):
            self.calls = 0

        def before_decision(self):
            self.calls += 1
            return super().before_decision()

    session = Counting()
    result, _, _ = _run([
        ToolCall(call_id="a", tool="skills.search", arguments={"query": "训练"}),
        FinalDecision(body="按计划执行，注意身体反馈。"),
    ], session=session)

    # Twice per round: once when the round starts, once immediately before the
    # provider sees anything.
    assert session.calls == 2 * result.trace["decision_count"]


def test_a_revoked_permission_stops_the_round_before_the_gateway():
    class Revoking(AdviceSession):
        def __init__(self):
            self.calls = 0

        def before_decision(self):
            self.calls += 1
            if self.calls >= 2:
                raise PermissionError("SCOPE_ACCESS_REVOKED")
            return super().before_decision()

    with pytest.raises(PermissionError, match="SCOPE_ACCESS_REVOKED"):
        _run([FinalDecision(body="按计划执行，注意身体反馈。")], session=Revoking())


def test_a_draft_write_is_not_replayed_after_a_transport_failure():
    attempts = []

    def handler(args, ctx):
        attempts.append(args.text)
        raise ConnectionError("socket closed")

    spec = ToolSpec(name="plan.submit", args_model=EchoArgs, effect="draft_write",
                    read_only=False, replay="never", handler=handler)

    with pytest.raises(Exception):
        _run([ToolCall(call_id="a", tool="plan.submit", arguments={"text": "draft"})],
             specs={"plan.submit": spec})

    # Exactly once: a submitted candidate must not become two writes because a
    # transport hiccup was retried.
    assert attempts == ["draft"]
