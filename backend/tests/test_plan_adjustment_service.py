"""One task, two repair rounds, and a decision the user still has to make.

The script below is the loop the plan asks for: the first candidate fails both
domains, the first repair fixes both and only training passes, the second repair
touches diet alone and passes. What the assertions are really about is that the
rounds are *claimed* (a failing candidate costs one), that the domain which
already passed is not rewritten to make the other one fit, and that a passing
candidate is still not an activated plan.

Every round is a separate ``execute``, which means a separate ``PlanTaskSession``.
Nothing survives in memory between them: the session re-reads the task, the last
candidate document and the reserved round scope from the repository.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from backend.agent.context_builder import ExecutionPrincipal
from backend.agent.contracts import AgentCommand
from backend.agent.decision import FinalDecision, ToolCall
from backend.agent.plan_adjustment.validation import PlanValidation
from backend.agent.runtime import AgentRuntime
from backend.agent.skills.catalog import SkillCatalog
from backend.agent.tasks.contracts import TaskRef
from backend.agent.tools.executor import ToolExecutor
from backend.agent.tools.handlers import BoundFitnessReads
from backend.agent.tools.registry import TASK_SPECS
from backend.agent.unified_coach import UnifiedCoachWorkflow
from backend.application.ports.agent_decision_gateway import AgentDecisionResult
from backend.application.use_cases.plan_adjustment import PlanAdjustmentService
from backend.domain.errors import ApplicationError
from backend.infrastructure.repositories.sqlite_plan_adjustment_repository import (
    SQLitePlanAdjustmentRepository,
)
from backend.infrastructure.repositories.sqlite_task_budget_repository import (
    SQLiteTaskBudgetRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS
from backend.schemas import GeneratedPlan
from backend.application.ports.plan_repository import StoredPlan

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)

# What every round in this file is asked to do. The prose is not task state --
# the task owns the grant, the constraints and the rounds -- so the tests restate
# the same request each time they spend one.
INSTRUCTIONS = "把训练和饮食都调整一下"

# Both domains start broken on purpose. Training has three consecutive
# high-intensity days; diet mentions the user's allergen in two meals.
BASE = {
    "workout_plan": {
        "summary": "每周四练",
        "weekly_training_days": 4,
        "rest_days": ["周日"],
        "days": [
            {"day": "周一", "type": "strength", "focus": "下肢", "intensity": "high",
             "exercises": [{"name": "深蹲", "sets": 4, "reps": 8}], "duration_min": 50},
            {"day": "周二", "type": "strength", "focus": "上肢", "intensity": "high",
             "exercises": [{"name": "卧推", "sets": 4, "reps": 8}], "duration_min": 50},
            {"day": "周三", "type": "strength", "focus": "全身", "intensity": "high",
             "exercises": [{"name": "硬拉", "sets": 3, "reps": 6}], "duration_min": 50},
            {"day": "周四", "type": "cardio", "focus": "有氧", "intensity": "low",
             "exercises": [{"name": "划船", "sets": 1, "reps": 1, "duration_min": 20}],
             "duration_min": 30},
        ],
    },
    "diet_plan": {
        "daily_calorie_target": 2000,
        "daily_protein_target": 140,
        "meals": ["花生燕麦粥", "花生酱三明治", "鸡胸沙拉"],
    },
    "validation": {"passed": False, "warnings": [], "violations": [], "repair_suggestions": []},
    "trace": {},
}

CONSTRAINTS = {
    "goal": "fat_loss",
    "weight_kg": 70.0,
    "daily_calorie_target": 2000.0,
    "daily_protein_target": 140.0,
    "allergies_or_restrictions": ["花生"],
    "safety_conditions": [],
    "action_restrictions": [],
    "available_equipment": ["barbell", "machine", "bodyweight", "dumbbell", "pull-up bar", "cable"],
    "session_minutes": 60,
    "forbidden_exercises": [],
}


class PlanStore:
    def __init__(self, plan=None):
        self.plan = deepcopy(plan or BASE)

    def get(self, user_id, plan_id):
        if plan_id != "p1":
            return None
        return StoredPlan(plan_id="p1", activated_at=NOW, kind="deterministic",
                          plan=GeneratedPlan.model_validate(self.plan))


class ForbiddenRepository:
    """The service must never read private records to validate a candidate."""

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


def _executor(session):
    principal = ExecutionPrincipal("alice", authorized_domains=frozenset({"profile", "training", "diet"}))
    return ToolExecutor(principal=principal, reads=BoundFitnessReads(ForbiddenRepository(), "alice"),
                        catalog=SkillCatalog(), authorize=lambda p: p.authorized_domains,
                        retriever=lambda *a, **k: [], language="zh-CN", specs=TASK_SPECS,
                        session=session)


def _runner(scripts):
    """One ``execute`` = one run, on the task's own budget binding."""
    queue = list(scripts)
    runs = []

    async def run(session, binding, request):
        gateway = ScriptedGateway(queue.pop(0))
        runs.append(gateway)
        runtime = AgentRuntime(
            task_budget_binding_factory=lambda user, ref: binding)
        command = AgentCommand("chat", request.instructions, "alice", language="zh-CN",
                               task_ref=TaskRef(binding.task_id, session.current().version))
        return await runtime.execute(command, UnifiedCoachWorkflow(gateway, _executor(session),
                                                                   session=session))

    run.gateways = runs
    return run


def _service(tmp_path, *, constraints=None, reviewer=None, scripts=(), plan=None,
             activations=None, constraints_source=None, **confirm_options):
    database = SQLiteDatabase(tmp_path / "plan.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    repository = SQLitePlanAdjustmentRepository(database, clock=lambda: NOW, ids=_ids())
    budgets = SQLiteTaskBudgetRepository(database)
    store = PlanStore(plan)
    runner = _runner(scripts)
    service = PlanAdjustmentService(
        repository, store, PlanValidation(),
        constraints_source=(constraints_source
                            or (lambda owner: dict(constraints or CONSTRAINTS))),
        head_revision=lambda owner: 1, runner=runner, budgets=budgets,
        reviewer=reviewer, activations=activations, **confirm_options)
    return service, repository, store, runner


def _day(index, **changes):
    old = deepcopy(BASE["workout_plan"]["days"][index])
    return {"domain": "training", "path": ["workout_plan", "days", index],
            "old_value": old, "new_value": dict(old, **changes),
            "reason": "调整训练安排", "evidence_refs": []}


def _meal(index, text):
    return {"domain": "diet", "path": ["diet_plan", "meals", index],
            "old_value": BASE["diet_plan"]["meals"][index], "new_value": text,
            "reason": "替换餐食", "evidence_refs": []}


def _submit(call_id, patches):
    return ToolCall(call_id=call_id, tool="plan.submit_candidate", arguments={"patches": patches})


def _read(call_id="read"):
    return ToolCall(call_id=call_id, tool="plan.read_base",
                    arguments={"fields": ["meta", "constraints", "training", "diet"]})


ROUND_0_PATCHES = [_day(0, focus="下肢力量"), _meal(2, "鸡胸沙拉配糙米")]
ROUND_1_PATCHES = [_day(2, intensity="medium"), _meal(0, "燕麦粥")]
ROUND_2_PATCHES = [_meal(1, "鸡蛋三明治")]
# Two rounds that fix nothing: each bundle edits an element the previous round
# left alone, so the old value is still what the working base holds, and both
# domains stay broken. This is what a model that has not found the problem looks
# like, and it must end in a stop rather than a third attempt.
FAIL_1_PATCHES = [_day(3, duration_min=35), _meal(1, "花生酱吐司")]
FAIL_2_PATCHES = [_day(2, duration_min=55), _meal(0, "花生燕麦粥加糖")]
# Everything fixed in one bundle: used where the only remaining problem is a
# constraint the plan cannot contain.
ROUND_FIX = ROUND_1_PATCHES + ROUND_2_PATCHES
ROUND_0_CANDIDATE = {"diet_plan": {"meals": []}, "workout_plan": {"days": []}}

# Round 0 edits both domains without fixing either: three high-intensity days in
# a row and two meals with the user's allergen are still there.
ROUND_0 = [_read(), _submit("c0", ROUND_0_PATCHES),
           FinalDecision(body="这一版还需要调整，我先说明问题在哪。")]
# Round 1 fixes both; only diet is left.
ROUND_1 = [_submit("c1", ROUND_1_PATCHES),
           FinalDecision(body="训练部分已经合格，饮食还有一项需要处理。")]
# Round 2 may touch diet only, and passes.
ROUND_2 = [_submit("c2", ROUND_2_PATCHES),
           FinalDecision(body="两个部分都已通过校验，等你确认后才会生效。")]


def _start(service, **overrides):
    options = dict(read_domains=frozenset({"training", "diet"}),
                   change_domains=frozenset({"training", "diet"}),
                   instructions="把训练和饮食都调整一下", key="create-1")
    options.update(overrides)
    return service.start("alice", "p1", **options)


def test_two_rounds_converge_and_still_wait_for_the_user(tmp_path):
    service, repo, store, runner = _service(tmp_path, scripts=[ROUND_0, ROUND_1, ROUND_2])
    before = deepcopy(store.plan)
    task = _start(service)

    first = asyncio.run(service.execute("alice", task["task_id"], task["version"], "exec-1", instructions=INSTRUCTIONS))
    assert first["task"]["failed_domains"] == ["diet", "training"]
    # The first candidate is round 0 and costs nothing, but seeing it fail claims
    # the first repair round before the next model call -- not after it.
    assert first["task"]["repair_rounds"] == 1
    round_0 = repo.latest_candidate("alice", task["task_id"])
    assert round_0.round_index == 0 and round_0.passed is False

    second = asyncio.run(service.execute("alice", task["task_id"],
                                         first["task"]["version"], "exec-2", instructions=INSTRUCTIONS))
    # Round 1 fixed training; the second round was claimed for diet alone.
    assert second["task"]["repair_rounds"] == 2
    assert second["task"]["failed_domains"] == ["diet"]
    assert second["receipt"] is None
    round_1 = repo.latest_candidate("alice", task["task_id"])
    assert round_1.round_index == 1 and round_1.passed is False

    third = asyncio.run(service.execute("alice", task["task_id"],
                                        second["task"]["version"], "exec-3", instructions=INSTRUCTIONS))
    snapshot = repo.get("alice", task["task_id"])
    assert snapshot.repair_rounds == 2
    assert snapshot.state == "awaiting_confirmation"
    assert snapshot.candidate_digest
    # Not activated: a candidate waits for a confirmation that does not exist yet.
    assert snapshot.state != "activated"
    assert third["task"]["candidate"]["digest"] == snapshot.candidate_digest
    assert third["task"]["candidate"]["expires_at"]

    round_2 = repo.latest_candidate("alice", task["task_id"])
    assert round_2.round_index == 2 and round_2.passed is True
    # The domain that already passed was not rewritten to make diet fit.
    assert round_2.domain_digests["training"] == round_1.domain_digests["training"]
    assert round_2.plan["workout_plan"] == round_1.plan["workout_plan"]

    # And the official plan is untouched by all three rounds.
    assert store.plan == before
    assert len(runner.gateways) == 3


def test_a_bundle_cannot_rewrite_the_domain_that_already_passed(tmp_path):
    # Round 2 is reserved for diet only, so a training patch is refused even
    # though the task holds a training change grant.
    rewrite_training = [_submit("c2", [_day(2, intensity="high"), _meal(1, "鸡蛋三明治")]),
                        FinalDecision(body="饮食已处理。")]
    service, repo, store, _ = _service(tmp_path, scripts=[ROUND_0, ROUND_1, rewrite_training])
    before = deepcopy(store.plan)
    task = _start(service)
    first = asyncio.run(service.execute("alice", task["task_id"], task["version"], "exec-1", instructions=INSTRUCTIONS))
    second = asyncio.run(service.execute("alice", task["task_id"], first["task"]["version"], "exec-2", instructions=INSTRUCTIONS))

    third = asyncio.run(service.execute("alice", task["task_id"], second["task"]["version"], "exec-3", instructions=INSTRUCTIONS))

    assert third["task"]["failed_domains"] == ["training"]
    assert [item["code"] for item in third["task"]["violations"]] == ["DOMAIN_FROZEN"]
    assert third["task"]["candidate"] is None
    assert repo.get("alice", task["task_id"]).repair_rounds == 2
    assert store.plan == before


def test_the_last_repair_ends_in_a_stop_instead_of_another_model_call(tmp_path):
    """Two failed repairs are a decision for the user, not a third attempt.

    The session could only *tell* a model the rounds were gone, and the loop
    discarded that frame: the next ``execute`` still ran a provider call whose
    every submission the store had to refuse. The stop is now written where it is
    decided, so the fourth ``execute`` costs nothing and the projection says what
    actually happened.
    """
    fail_1 = [_submit("c1", FAIL_1_PATCHES), FinalDecision(body="训练和饮食都还没通过。")]
    fail_2 = [_submit("c2", FAIL_2_PATCHES), FinalDecision(body="仍然没有通过。")]
    service, repo, store, runner = _service(tmp_path, scripts=[ROUND_0, fail_1, fail_2])
    before = deepcopy(store.plan)
    task = _start(service)

    first = asyncio.run(service.execute("alice", task["task_id"], task["version"], "exec-1", instructions=INSTRUCTIONS))
    second = asyncio.run(service.execute("alice", task["task_id"], first["task"]["version"], "exec-2", instructions=INSTRUCTIONS))
    third = asyncio.run(service.execute("alice", task["task_id"], second["task"]["version"], "exec-3", instructions=INSTRUCTIONS))

    assert third["task"]["repair_rounds"] == 2
    assert third["task"]["failed_domains"] == ["diet", "training"]
    assert third["task"]["candidate"] is None
    assert repo.get("alice", task["task_id"]).state == "repairing"

    stopped = asyncio.run(service.execute("alice", task["task_id"],
                                          third["task"]["version"], "exec-4", instructions=INSTRUCTIONS))

    assert stopped["task"]["state"] == "awaiting_user_decision"
    assert stopped["task"]["repair_rounds"] == 2
    # No fourth run, and no plan written by a task that never produced a candidate.
    assert len(runner.gateways) == 3
    assert store.plan == before
    assert repo.get("alice", task["task_id"]).state == "awaiting_user_decision"


def test_a_missing_constraint_stops_without_spending_a_round(tmp_path):
    unknown_equipment = dict(CONSTRAINTS)
    unknown_equipment.pop("available_equipment")
    service, repo, _, _ = _service(
        tmp_path, constraints=unknown_equipment,
        scripts=[[_submit("c0", ROUND_FIX), FinalDecision(body="缺一项信息。")]])
    task = _start(service)

    result = asyncio.run(service.execute("alice", task["task_id"], task["version"], "exec-1", instructions=INSTRUCTIONS))

    # A patch cannot invent equipment, so the task asks instead of looping. No
    # round is spent and no candidate is recorded: this was not an attempt at the
    # plan, and the retry after ``answer`` needs the round slot to be free.
    assert result["task"]["state"] == "awaiting_user_decision"
    assert result["task"]["repair_rounds"] == 0
    assert result["task"]["missing_constraints"] == ["constraints.available_equipment"]
    assert repo.latest_candidate("alice", task["task_id"]) is None


def test_answers_resume_the_task_that_asked(tmp_path):
    unknown_equipment = dict(CONSTRAINTS)
    unknown_equipment.pop("available_equipment")
    fix = [_submit("c0", ROUND_FIX), FinalDecision(body="两个部分都已通过校验。")]
    service, repo, _, _ = _service(
        tmp_path, constraints=unknown_equipment,
        scripts=[[_submit("c0", ROUND_FIX), FinalDecision(body="缺一项信息。")], fix])
    task = _start(service)
    stopped = asyncio.run(service.execute("alice", task["task_id"], task["version"], "exec-1", instructions=INSTRUCTIONS))

    answered = service.answer("alice", task["task_id"], stopped["task"]["version"],
                              {"available_equipment": CONSTRAINTS["available_equipment"]},
                              key="answer-1")
    assert answered["state"] == "generating"
    assert repo.constraints("alice", task["task_id"])["available_equipment"]

    resumed = asyncio.run(service.execute("alice", task["task_id"], answered["version"], "exec-2", instructions=INSTRUCTIONS))
    assert resumed["task"]["state"] == "awaiting_confirmation"
    assert resumed["task"]["candidate"]


def test_a_reserved_round_is_reused_after_a_disconnect(tmp_path):
    # The round was claimed and the process ended before submitting. A later run
    # continues that round instead of claiming a second one.
    gave_up = [FinalDecision(body="这一版没能通过校验，先说明问题。")]
    service, repo, _, _ = _service(tmp_path, scripts=[ROUND_0, gave_up, ROUND_1])
    task = _start(service)
    first = asyncio.run(service.execute("alice", task["task_id"], task["version"], "exec-1", instructions=INSTRUCTIONS))
    reserved = repo.get("alice", task["task_id"])
    assert reserved.repair_rounds == 1 and reserved.active_round_id
    # The reservation recorded the domains that failed, before any revision call.
    assert repo.round_scope("alice", task["task_id"]) == frozenset({"training", "diet"})

    asyncio.run(service.execute("alice", task["task_id"], first["task"]["version"], "exec-2", instructions=INSTRUCTIONS))
    assert repo.get("alice", task["task_id"]).repair_rounds == 1

    asyncio.run(service.execute("alice", task["task_id"],
                                first["task"]["version"], "exec-3", instructions=INSTRUCTIONS))
    # The submission landed in the round that was already claimed, not in a new one.
    assert repo.latest_candidate("alice", task["task_id"]).round_index == 1


def test_a_replayed_submission_returns_the_same_candidate(tmp_path):
    service, repo, _, _ = _service(tmp_path, scripts=[])
    task = _start(service)
    snapshot = repo.get("alice", task["task_id"])
    bundle = _bundle(ROUND_0_PATCHES)
    operation = f"{task['task_id']}:0:{bundle.digest()[:16]}"

    first = repo.submit_bundle("alice", task["task_id"], snapshot.version, operation,
                               bundle, _verdict(bundle), ROUND_0_CANDIDATE)
    replay = repo.submit_bundle("alice", task["task_id"], snapshot.version, operation,
                                bundle, _verdict(bundle), ROUND_0_CANDIDATE)

    # The receipt is matched before the version check, so the retry with the
    # original version gets its own answer instead of an unresolvable conflict.
    assert replay.version == first.version == snapshot.version + 1
    assert repo.latest_candidate("alice", task["task_id"]).digest == bundle.digest()


def test_an_unreviewed_candidate_is_not_published(tmp_path):
    def refuse(candidate):
        return "CANDIDATE_REFUSED"

    service, repo, _, _ = _service(
        tmp_path, reviewer=refuse,
        scripts=[[_submit("c0", ROUND_FIX), FinalDecision(body="两个部分都已通过校验，等你确认。")]])
    task = _start(service)

    result = asyncio.run(service.execute("alice", task["task_id"], task["version"], "exec-1", instructions=INSTRUCTIONS))

    assert result["task"]["state"] == "awaiting_user_decision"
    assert result["receipt"] is None
    assert repo.get("alice", task["task_id"]).state == "awaiting_user_decision"


def test_an_unavailable_reviewer_publishes_nothing(tmp_path):
    def unavailable(candidate):
        raise RuntimeError("reviewer offline")

    service, repo, _, _ = _service(
        tmp_path, reviewer=unavailable,
        scripts=[[_submit("c0", ROUND_FIX), FinalDecision(body="两个部分都已通过校验。")]])
    task = _start(service)

    result = asyncio.run(service.execute("alice", task["task_id"], task["version"], "exec-1", instructions=INSTRUCTIONS))

    assert result["task"]["state"] == "awaiting_user_decision"
    assert result["receipt"] is None
    # The candidate is on record -- what was produced is not erased -- but the
    # answer carries no receipt, so nothing about it is confirmable.
    assert repo.get("alice", task["task_id"]).state == "awaiting_user_decision"


def test_a_training_only_task_cannot_touch_diet(tmp_path):
    service, repo, _, _ = _service(
        tmp_path,
        scripts=[[_submit("c0", [_meal(0, "燕麦粥")]),
                  FinalDecision(body="只能调整训练部分。")]])
    task = _start(service, read_domains=frozenset({"training", "diet"}),
                  change_domains=frozenset({"training"}))
    # Diet is readable but not writable: the difference is the pending decision.
    assert task["state"] == "collecting"
    granted = service.grant("alice", task["task_id"], task["version"],
                            frozenset({"training", "diet"}), frozenset({"training"}),
                            "allow", key="grant-1")
    assert granted["state"] == "generating"

    result = asyncio.run(service.execute("alice", task["task_id"], granted["version"], "exec-1", instructions=INSTRUCTIONS))

    assert [item["code"] for item in result["task"]["violations"]] == ["PATCH_SCOPE"]
    # The refusal is on record, but it produced no candidate document.
    assert repo.latest_candidate("alice", task["task_id"]).plan is None


def test_confirm_refuses_before_the_atomic_activation_exists(tmp_path):
    service, _, store, _ = _service(tmp_path, scripts=[ROUND_0, ROUND_1, ROUND_2])
    before = deepcopy(store.plan)
    task = _start(service)
    first = asyncio.run(service.execute("alice", task["task_id"], task["version"], "exec-1", instructions=INSTRUCTIONS))
    second = asyncio.run(service.execute("alice", task["task_id"], first["task"]["version"], "exec-2", instructions=INSTRUCTIONS))
    third = asyncio.run(service.execute("alice", task["task_id"], second["task"]["version"], "exec-3", instructions=INSTRUCTIONS))

    with pytest.raises(ApplicationError, match="PLAN_CONFIRMATION_NOT_ENABLED"):
        service.confirm("alice", task["task_id"], third["task"]["version"], 1,
                        third["task"]["candidate"]["digest"], key="confirm-1")
    assert store.plan == before


def test_a_candidate_arriving_after_confirmation_is_refused(tmp_path):
    service, repo, _, _ = _service(tmp_path, scripts=[ROUND_0, ROUND_1, ROUND_2])
    task = _start(service)
    first = asyncio.run(service.execute("alice", task["task_id"], task["version"], "exec-1", instructions=INSTRUCTIONS))
    second = asyncio.run(service.execute("alice", task["task_id"], first["task"]["version"], "exec-2", instructions=INSTRUCTIONS))
    asyncio.run(service.execute("alice", task["task_id"], second["task"]["version"], "exec-3", instructions=INSTRUCTIONS))
    snapshot = repo.get("alice", task["task_id"])

    with pytest.raises(ApplicationError, match="STATE_TRANSITION"):
        repo.submit_bundle("alice", task["task_id"], snapshot.version, "late-1",
                           _bundle([_meal(1, "鸡蛋三明治")]),
                           _verdict(_bundle([_meal(1, "鸡蛋三明治")])))


def _bundle(patches):
    from backend.domain.plan_adjustment import CandidateBundle, Patch
    return CandidateBundle(patches=tuple(
        Patch(domain=item["domain"], path=tuple(item["path"]), old_value=item["old_value"],
              new_value=item["new_value"], reason=item["reason"], evidence_refs=())
        for item in patches))


def _verdict(bundle):
    from backend.domain.plan_adjustment import CandidateVerdict
    return CandidateVerdict(candidate_id=bundle.digest()[:32], digest=bundle.digest(),
                            passed=True, dependency_digest="d" * 64)


def test_a_second_protocol_failure_ends_the_run_but_keeps_the_budget(tmp_path):
    broken = [{"kind": "final"}, {"kind": "final"}]
    service, repo, _, _ = _service(tmp_path, scripts=[broken])
    task = _start(service)

    with pytest.raises(ValueError, match="AGENT_PROTOCOL_FAILED"):
        asyncio.run(service.execute("alice", task["task_id"], task["version"], "exec-1", instructions=INSTRUCTIONS))

    snapshot = repo.get("alice", task["task_id"])
    assert snapshot.state == "generating"
    # The failed run did not hand the task a fresh ceiling.
    budget = SQLiteTaskBudgetRepository(repo.database).get_snapshot("alice", task["task_id"])
    assert budget.call_limit == 36 and budget.spent_calls > 0


def test_execute_reuses_one_budget_per_task(tmp_path):
    service, repo, _, _ = _service(tmp_path, scripts=[ROUND_0, ROUND_1, ROUND_2])
    task = _start(service)
    first = asyncio.run(service.execute("alice", task["task_id"], task["version"], "exec-1", instructions=INSTRUCTIONS))
    after_first = SQLiteTaskBudgetRepository(repo.database).get_snapshot("alice", task["task_id"])
    asyncio.run(service.execute("alice", task["task_id"], first["task"]["version"], "exec-2", instructions=INSTRUCTIONS))
    after_second = SQLiteTaskBudgetRepository(repo.database).get_snapshot("alice", task["task_id"])

    assert after_second.call_limit == after_first.call_limit
    assert after_second.spent_calls > after_first.spent_calls
    assert after_second.spent_calls <= after_second.call_limit


def test_a_foreign_task_is_not_found(tmp_path):
    service, repo, _, _ = _service(tmp_path, scripts=[])
    task = repo.create_task("bob", base_plan_id="p1", base_head_revision=1,
                            read_domains=frozenset({"training"}),
                            change_domains=frozenset({"training"}), constraints={}, key="bob-1")

    with pytest.raises(ApplicationError, match="TASK_NOT_FOUND"):
        service.get("alice", task.task_id)


def test_cancel_is_terminal(tmp_path):
    service, repo, _, _ = _service(tmp_path, scripts=[])
    task = _start(service)

    cancelled = service.cancel("alice", task["task_id"], task["version"], key="cancel-1")

    assert cancelled["state"] == "cancelled"
    with pytest.raises(ApplicationError, match="STATE_TRANSITION"):
        asyncio.run(service.execute("alice", task["task_id"], cancelled["version"], "exec-1", instructions=INSTRUCTIONS))


# ---------------------------------------------------------------- confirmation

# A document that passes every check the confirmation re-runs. The rounds above
# deliberately never produce one, because they are about repair; this one exists
# so the confirmation path can be reached without a scripted model.
CONFIRMABLE = {
    "diet_plan": {"meals": ["燕麦粥配鸡蛋", "鸡胸沙拉", "糙米饭配牛肉"],
                  "daily_calorie_target": 2000, "daily_protein_target": 140},
    "workout_plan": {
        "summary": "每周三练", "weekly_training_days": 3,
        "rest_days": ["周三", "周六", "周日"],
        "days": [
            {"day": "周一", "type": "strength", "focus": "下肢", "intensity": "medium",
             "exercises": [{"name": "深蹲", "sets": 4, "reps": 8}], "duration_min": 45},
            {"day": "周二", "type": "cardio", "focus": "有氧", "intensity": "low",
             "exercises": [{"name": "快走"}], "duration_min": 30},
            {"day": "周四", "type": "strength", "focus": "上肢", "intensity": "medium",
             "exercises": [{"name": "俯卧撑", "sets": 3, "reps": 12}], "duration_min": 40},
        ],
    },
}


HARD_FIELDS = ("allergies_or_restrictions", "safety_conditions", "action_restrictions",
               "available_equipment", "session_minutes", "forbidden_exercises")


class StubActivations:
    """The store's half of a confirmation, without a database.

    It does exactly what the real one does at this seam: read the constraint
    snapshot, build the context the verifier reads, call it, and keep what it
    produced. ``versioned=False`` is the deployment whose hard constraints are
    still file-backed, and ``snapshot=False`` is one with no versioned store at
    all -- two different refusals that must not be confused with "unchanged".
    """

    def __init__(self, *, reviewed="same", constraints=None, document=None,
                 versioned=True, snapshot=True):
        self.reviewed = reviewed
        # ``constraints`` is the live source; ``frozen`` is what the task recorded
        # when it was created. Keeping them apart is the whole point: the real
        # repository reads the frozen copy out of the task row and the live one on
        # its own connection, so a stub that shared one mapping would never be
        # able to show drift.
        self.constraints = constraints or CONSTRAINTS
        self.frozen = dict(self.constraints)
        self.document = document or CONFIRMABLE
        self.versioned = versioned
        self.snapshot = snapshot
        self.documents = []
        self.contexts = []

    def _snapshot(self):
        from backend.application.ports.profile_target_repository import (
            ConstraintSnapshot,
        )

        versions = {field: (f"v-{field}" if self.versioned else None)
                    for field in HARD_FIELDS}
        return ConstraintSnapshot(constraints=dict(self.constraints), versions=versions)

    def activate(self, owner, *, task_id, expected_version, expected_head_revision,
                 candidate_digest, operation_key, verify):
        from backend.application.ports.plan_repository import (
            ActivationContext,
            PlanActivationReceipt,
            PlanHead,
        )

        context = ActivationContext(
            user_id=owner, task_id=task_id, base_plan_id="p1",
            base_head_revision=expected_head_revision,
            constraints=dict(self.frozen),
            reviewed_digest=(candidate_digest if self.reviewed == "same" else self.reviewed),
            candidate_id="c1", candidate_digest=candidate_digest,
            candidate_plan=deepcopy(self.document),
            head=PlanHead(plan_id="p1", revision=expected_head_revision, updated_at=NOW),
            base_plan=None,
            constraints_at_write=self._snapshot() if self.snapshot else None,
        )
        self.contexts.append(context)
        self.documents.append(verify(context))
        return PlanActivationReceipt(
            plan_id="plan-confirmed", head_revision=expected_head_revision + 1,
            activated_at=NOW, kind="agent_adjusted", based_on_plan_id="p1")


def _awaiting(tmp_path, **options):
    """A task whose candidate passed and is waiting for the user."""
    service, repo, store, runner = _service(tmp_path, scripts=[ROUND_0, ROUND_1, ROUND_2],
                                            **options)
    task = _start(service)
    first = asyncio.run(service.execute("alice", task["task_id"], task["version"], "exec-1", instructions=INSTRUCTIONS))
    second = asyncio.run(service.execute("alice", task["task_id"], first["task"]["version"],
                                         "exec-2", instructions=INSTRUCTIONS))
    third = asyncio.run(service.execute("alice", task["task_id"], second["task"]["version"],
                                        "exec-3", instructions=INSTRUCTIONS))
    return service, repo, task, third, runner


def test_confirm_writes_the_reviewed_document(tmp_path):
    activations = StubActivations()
    service, repo, task, third, _ = _awaiting(tmp_path, activations=activations)

    result = service.confirm("alice", task["task_id"], third["task"]["version"], 1,
                             third["task"]["candidate"]["digest"], key="confirm-1")

    assert result["plan"]["plan_id"] == "plan-confirmed"
    assert result["plan"]["head_revision"] == 2
    assert result["replayed"] is False
    # The document the store would insert is the one the verifier re-checked,
    # and it carries the stamp every stored plan needs.
    assert activations.documents[0]["validation"]["passed"] is True
    assert activations.documents[0]["diet_plan"] == CONFIRMABLE["diet_plan"]


@pytest.mark.parametrize("stub", [{"versioned": False}, {"snapshot": False}],
                         ids=["file-backed-constraints", "no-versioned-store"])
def test_confirm_refuses_a_source_that_cannot_be_versioned(tmp_path, stub):
    # Two shapes of the same refusal: a store that cannot name where a hard
    # constraint came from, and a deployment with no such store at all. Neither
    # may be read as "nothing changed".
    activations = StubActivations(**stub)
    service, _, task, third, _ = _awaiting(tmp_path, activations=activations)

    with pytest.raises(ApplicationError, match="CONSTRAINT_SOURCE_UNVERSIONED"):
        service.confirm("alice", task["task_id"], third["task"]["version"], 1,
                        third["task"]["candidate"]["digest"], key="confirm-1")
    assert activations.documents == []


def test_confirm_refuses_when_the_profile_moved_under_the_candidate(tmp_path):
    source = dict(CONSTRAINTS)
    # The store reads the same live mapping the task was created from, so the
    # mutation below is exactly what a profile write looks like from here.
    activations = StubActivations(constraints=source)
    service, _, task, third, _ = _awaiting(
        tmp_path, activations=activations,
        constraints_source=lambda owner: dict(source))
    # The user added an allergy after the candidate was reviewed.
    source["allergies_or_restrictions"] = ["花生", "海鲜"]

    with pytest.raises(ApplicationError, match="CONSTRAINT_CHANGED"):
        service.confirm("alice", task["task_id"], third["task"]["version"], 1,
                        third["task"]["candidate"]["digest"], key="confirm-1")
    assert activations.documents == []


def test_confirm_refuses_when_a_safety_condition_is_declared_after_the_review(tmp_path):
    """A declared condition changes what the candidate was reviewed against.

    It gates the diet, so adding one is not a cosmetic profile edit: the meal plan
    on screen was produced under a rule that no longer applies.
    """
    source = dict(CONSTRAINTS)
    activations = StubActivations(constraints=source)
    service, _, task, third, _ = _awaiting(
        tmp_path, activations=activations,
        constraints_source=lambda owner: dict(source))
    source["safety_conditions"] = ["pregnancy"]

    with pytest.raises(ApplicationError, match="CONSTRAINT_CHANGED"):
        service.confirm("alice", task["task_id"], third["task"]["version"], 1,
                        third["task"]["candidate"]["digest"], key="confirm-1")
    assert activations.documents == []


def test_confirm_requires_a_review_when_the_policy_tightens(tmp_path):
    activations = StubActivations(reviewed="a-different-digest")
    service, _, task, third, _ = _awaiting(
        tmp_path, activations=activations, review_required=True)

    with pytest.raises(ApplicationError, match="CANDIDATE_REVIEW_REQUIRED"):
        service.confirm("alice", task["task_id"], third["task"]["version"], 1,
                        third["task"]["candidate"]["digest"], key="confirm-1")
    assert activations.documents == []


def test_confirm_refuses_a_document_that_no_longer_validates(tmp_path):
    broken = deepcopy(CONFIRMABLE)
    # A document whose meals are no longer a list cannot be checked at all, so it
    # must not be stored as if it had been.
    broken["diet_plan"]["meals"] = "燕麦粥配鸡蛋"
    activations = StubActivations(document=broken)
    service, _, task, third, _ = _awaiting(tmp_path, activations=activations)

    with pytest.raises(ApplicationError, match="CANDIDATE_INVALID"):
        service.confirm("alice", task["task_id"], third["task"]["version"], 1,
                        third["task"]["candidate"]["digest"], key="confirm-1")


def _real_wiring(tmp_path, *, allergies=None):
    """The production store, not a stub: real database, real profile reader.

    ``allergies`` is what the versioned safety record holds. ``None`` leaves the
    account unmigrated, which is the state of every account whose restrictions
    still live only in ``user_profile.json``.
    """
    from backend.application.ports.profile_target_repository import (
        GoalVersionInput,
        ProfileVersionInput,
        SafetyVersionInput,
        TargetVersionInput,
    )
    from backend.infrastructure.repositories.sqlite_plan_repository import (
        SQLitePlanRepository,
    )
    from backend.infrastructure.repositories.sqlite_profile_target_repository import (
        SQLiteProfileTargetRepository,
    )

    service, repo, task, third, _ = _awaiting(tmp_path)
    profiles = SQLiteProfileTargetRepository(repo.database, clock=lambda: NOW)
    setup = profiles.bootstrap(
        "alice",
        ProfileVersionInput(age=30, height_cm=175.0, weight_kg=70.0,
                            energy_parameter="male", activity_level="moderate",
                            auto_target_disabled=False, safety_conditions=(),
                            effective_from="2026-10-01"),
        GoalVersionInput(goal="fat_loss", effective_from="2026-10-01"),
    )
    profiles.append_target("alice", TargetVersionInput(
        profile_version_id=setup.profile.id,
        overall_goal_version_id=setup.goal.id,
        calories=2000, carbs=250, protein=140, fat=60,
        source="manual", formula_version=None,
        rationale={"confirmed_warnings": []}, effective_from="2026-10-02"))
    if allergies is not None:
        profiles.append_safety_if_changed(
            "alice", SafetyVersionInput(allergies_or_restrictions=allergies))
    # Same clock as the task store, or the real one would judge the fixture's
    # timestamps against today and call an unexpired candidate expired.
    plans = SQLitePlanRepository(repo.database, clock=lambda: NOW,
                                 constraints_reader=profiles.constraint_snapshot_with)
    plans.save("alice", StoredPlan(plan_id="p1", activated_at=NOW,
                                   kind="deterministic", plan=BASE))
    service.activations = plans
    return service, plans, task, third


def test_confirmation_refuses_while_the_allergy_list_has_no_version(tmp_path):
    """The state of every account that has not been migrated or re-saved.

    The list still lives only in ``user_profile.json``, which has no version, so
    "these are the restrictions the candidate was reviewed against" has no answer
    that can be reproduced. Approving on the strength of it is approving a check
    nobody can re-run.
    """
    service, plans, task, third = _real_wiring(tmp_path)

    with pytest.raises(ApplicationError, match="CONSTRAINT_SOURCE_UNVERSIONED"):
        service.confirm("alice", task["task_id"], third["task"]["version"], 1,
                        third["task"]["candidate"]["digest"], key="confirm-1")
    assert len(plans.list("alice")) == 1


def test_versioning_the_allergy_list_is_what_unblocks_confirmation(tmp_path):
    """The end of the write path this task exists for.

    Same account, same candidate, same everything -- one extra row. That row is
    the whole difference between "refused because the check cannot be reproduced"
    and a confirmed plan, which is why the profile save now writes it.
    """
    service, plans, task, third = _real_wiring(tmp_path, allergies=("花生",))

    result = service.confirm("alice", task["task_id"], third["task"]["version"], 1,
                             third["task"]["candidate"]["digest"], key="confirm-1")

    assert result["plan"]["head_revision"] == 2
    assert result["plan"]["based_on_plan_id"] == "p1"
    stored = plans.get("alice", result["plan"]["plan_id"])
    candidate = service.repository.latest_candidate("alice", task["task_id"]).plan
    # What was stored is the document the verifier re-checked, not the bundle the
    # model sent: the two are equal only because the merge was applied once.
    assert stored.plan.diet_plan == candidate["diet_plan"]
    assert stored.plan.validation.passed is True
    assert plans.current_head("alice").revision == 2
