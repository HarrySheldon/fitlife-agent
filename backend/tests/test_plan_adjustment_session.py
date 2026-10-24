"""A candidate only exists inside a bound task, and only the repository says so.

The scripts below are what the model is allowed to do: read the bound base plan,
submit a bounded bundle, then explain. Everything else -- creating a task,
widening a grant, reserving a round, activating a plan -- has no tool.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from backend.agent.context_builder import ExecutionPrincipal
from backend.agent.contracts import AgentCommand
from backend.agent.decision import FinalDecision, ToolCall
from backend.agent.plan_adjustment.session import PlanTaskSession
from backend.agent.runtime import AgentRuntime
from backend.agent.skills.catalog import SkillCatalog
from backend.agent.tools.executor import ToolExecutor
from backend.agent.tools.handlers import BoundFitnessReads
from backend.agent.tools.registry import SPECS, TASK_SPECS
from backend.agent.unified_coach import UnifiedCoachWorkflow
from backend.application.ports.agent_decision_gateway import AgentDecisionResult
from backend.domain.plan_adjustment import CandidateVerdict, Violation
from backend.infrastructure.repositories.sqlite_plan_adjustment_repository import (
    SQLitePlanAdjustmentRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)

BASE = {
    "workout_plan": {
        "summary": "每周三次全身训练",
        "weekly_training_days": 3,
        "rest_days": ["周日"],
        "days": [{"day": "周一", "type": "strength", "focus": "胸", "intensity": "medium",
                  "exercises": [{"name": "卧推", "sets": 3, "reps": 8, "rest_seconds": 90}],
                  "duration_min": 45}],
    },
    "diet_plan": {"daily_calorie_target": 2000, "daily_protein_target": 140,
                  "meals": ["燕麦加鸡蛋", "鸡胸肉沙拉", "牛肉面"]},
}


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


def _ids():
    state = {"n": 0}

    def next_id():
        state["n"] += 1
        return f"id-{state['n']:04d}"

    return next_id


def _repository(tmp_path):
    database = SQLiteDatabase(tmp_path / "plan.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    return SQLitePlanAdjustmentRepository(database, clock=lambda: NOW, ids=_ids())


def _task(repo, *, read=frozenset({"training"}), change=frozenset({"training"})):
    task = repo.create_task("alice", base_plan_id="p1", base_head_revision=1,
                            read_domains=read, change_domains=change,
                            constraints={"allergies_or_restrictions": [], "action_restrictions": []},
                            key="create-1")
    return repo.grant("alice", task.task_id, task.version, read, change, key="grant-1")


class StubValidation:
    """Stands in for Task 5's deterministic evaluator."""

    def __init__(self, factory):
        self.factory = factory
        self.calls = []

    def evaluate(self, base, bundle, constraints):
        self.calls.append((deepcopy(base), bundle, constraints))
        return self.factory(bundle)


def _passed(bundle):
    return CandidateVerdict(candidate_id=bundle.digest()[:32], digest=bundle.digest(),
                            passed=True, failed_domains=(), violations=(),
                            dependency_digest="d" * 64)


def _failed(bundle, code="PATCH_STALE"):
    return CandidateVerdict(candidate_id=bundle.digest()[:32], digest=bundle.digest(),
                            passed=False, failed_domains=("training",),
                            violations=(Violation(code=code, domain="training",
                                                  path="workout_plan.days.0"),),
                            dependency_digest="d" * 64)


def _executor(specs, session=None):
    principal = ExecutionPrincipal("owner", authorized_domains=frozenset({"profile", "training"}))
    return ToolExecutor(principal=principal, reads=BoundFitnessReads(ForbiddenRepository(), "owner"),
                        catalog=SkillCatalog(), authorize=lambda p: p.authorized_domains,
                        retriever=lambda *a, **k: [], language="zh-CN", specs=specs,
                        session=session)


def _run(decisions, specs, session=None):
    executor = _executor(specs, session)
    gateway = ScriptedGateway(decisions)
    command = AgentCommand("chat", "教练你好，我需要今天练胸，给出一份完整的训练计划", "owner", language="zh-CN")
    result = asyncio.run(AgentRuntime().execute(
        command, UnifiedCoachWorkflow(gateway, executor, session=session)))
    return result, executor


def _session(repo, task, validation):
    return PlanTaskSession(repo, "alice", task.task_id, validation,
                           load_base=lambda owner, plan_id, revision: deepcopy(BASE))


def _patch_arguments(new_intensity="high"):
    day = deepcopy(BASE["workout_plan"]["days"][0])
    replacement = dict(day, intensity=new_intensity)
    return {"patches": [{"domain": "training", "path": ["workout_plan", "days", 0],
                         "old_value": day, "new_value": replacement,
                         "reason": "提高强度", "evidence_refs": []}]}


def test_plan_tools_are_refused_without_a_bound_task():
    executor = _executor(TASK_SPECS, session=None)

    from backend.agent.runtime import RuntimeContext

    for call_id, name, arguments in (
            ("a", "plan.read_base", {"fields": ["training"]}),
            ("b", "plan.submit_candidate", _patch_arguments())):
        result = asyncio.run(executor.execute(
            executor.principal, ToolCall(call_id=call_id, tool=name, arguments=arguments),
            RuntimeContext()))
        assert result["status"] == "denied"
        assert result["code"] == "TASK_SESSION_REQUIRED"
    # The handler -- the only path to a repository -- never ran.
    assert executor.executions == 0


def test_plain_advice_does_not_advertise_task_tools():
    from backend.agent.tools.registry import tool_descriptions

    names = {item["name"] for item in tool_descriptions(SPECS)}
    assert "plan.read_base" not in names
    assert {"plan.read_base", "plan.submit_candidate"} <= {item["name"] for item in tool_descriptions(TASK_SPECS)}


def test_a_training_task_cannot_read_the_diet_plan(tmp_path):
    repo = _repository(tmp_path)
    task = _task(repo)
    session = _session(repo, task, StubValidation(_passed))

    assert set(session.read_base(["training", "meta"])) == {"training", "meta"}
    with pytest.raises(PermissionError, match="FIELD_NOT_AUTHORIZED"):
        session.read_base(["diet"])
    with pytest.raises(PermissionError, match="FIELD_NOT_AUTHORIZED"):
        session.read_base(["workout_plan"])


def test_the_candidate_comes_from_the_submitted_bundle_and_the_plan_is_untouched(tmp_path):
    repo = _repository(tmp_path)
    task = _task(repo)
    before = deepcopy(BASE)
    validation = StubValidation(_passed)
    session = _session(repo, task, validation)

    result, _ = _run([
        ToolCall(call_id="a", tool="plan.read_base", arguments={"fields": ["training"]}),
        ToolCall(call_id="b", tool="plan.submit_candidate", arguments=_patch_arguments()),
        FinalDecision(body="已把周一的强度调高，确认后生效。"),
    ], TASK_SPECS, session=session)

    receipt = result.task_receipt
    assert receipt["state"] == "awaiting_confirmation"
    assert receipt["candidate_digest"] == validation.calls[0][1].digest()
    assert receipt["candidate_expires_at"]
    # Nothing was written to the plan: only a candidate exists.
    assert BASE == before


def test_a_final_answer_cannot_claim_the_plan_was_activated(tmp_path):
    repo = _repository(tmp_path)
    task = _task(repo)
    session = _session(repo, task, StubValidation(_passed))

    with pytest.raises(ValueError, match="UNCONFIRMED_WRITE_CLAIM"):
        _run([FinalDecision(body="计划已激活，明天就可以按新安排训练。")], TASK_SPECS, session=session)


def test_a_final_answer_without_a_candidate_carries_no_receipt(tmp_path):
    repo = _repository(tmp_path)
    task = _task(repo)
    session = _session(repo, task, StubValidation(_passed))

    result, _ = _run([FinalDecision(body="先说清楚你要练哪一天，我再给建议。")], TASK_SPECS, session=session)

    assert result.task_receipt is None


def test_an_unknown_or_foreign_task_fails_before_any_model_call(tmp_path):
    repo = _repository(tmp_path)
    other = repo.create_task("bob", base_plan_id="p1", base_head_revision=1,
                             read_domains=frozenset({"training"}),
                             change_domains=frozenset({"training"}), constraints={}, key="bob-1")
    session = PlanTaskSession(repo, "alice", other.task_id, StubValidation([]),
                              load_base=lambda *args: deepcopy(BASE))
    gateway = ScriptedGateway([FinalDecision(body="随便说点什么。")])

    with pytest.raises(KeyError):
        asyncio.run(AgentRuntime().execute(
            AgentCommand("chat", "今天练胸", "owner", language="zh-CN"),
            UnifiedCoachWorkflow(gateway, _executor(TASK_SPECS, session), session=session)))
    assert gateway.requests == []


class RecordingSession(PlanTaskSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.frames = []

    def before_decision(self):
        frame = super().before_decision()
        self.frames.append(frame)
        return frame


def test_a_failed_candidate_reserves_the_next_round_before_the_model_returns(tmp_path):
    repo = _repository(tmp_path)
    task = _task(repo)
    validation = StubValidation(_failed)
    session = RecordingSession(repo, "alice", task.task_id, validation,
                               load_base=lambda owner, plan_id, revision: deepcopy(BASE))

    _run([
        ToolCall(call_id="a", tool="plan.submit_candidate", arguments=_patch_arguments()),
        FinalDecision(body="这一项没能通过校验，我先说明问题在哪。"),
    ], TASK_SPECS, session=session)

    # The round was claimed before the second decision, not after a candidate
    # arrived: a model that stalls still costs the round.
    repair_frames = [frame for frame in session.frames if frame.phase == "repairing"]
    assert repair_frames
    assert repair_frames[0].state["failed_domains"] == ["training"]
    assert repair_frames[0].state["round"] == 1
    snapshot = repo.get("alice", task.task_id)
    assert snapshot.repair_rounds == 1
    assert snapshot.active_round_id is not None


def test_running_out_of_rounds_stops_instead_of_looping(tmp_path):
    repo = _repository(tmp_path)
    task = _task(repo)
    validation = StubValidation(_failed)
    session = _session(repo, task, validation)

    # Round 0 is the first candidate; rounds 1 and 2 are the two repairs.
    for index in range(3):
        session.before_decision()
        session.submit_candidate([_patch_model(index)])

    frame = session.before_decision()
    assert frame.phase == "awaiting_user_decision"
    assert frame.state["reason"] == "REPAIR_LIMIT"


def _patch_model(index):
    from backend.domain.plan_adjustment import Patch
    day = deepcopy(BASE["workout_plan"]["days"][0])
    return Patch(domain="training", path=("workout_plan", "days", 0), old_value=day,
                 new_value=dict(day, intensity="high"), reason=f"第{index}次修订",
                 evidence_refs=())
