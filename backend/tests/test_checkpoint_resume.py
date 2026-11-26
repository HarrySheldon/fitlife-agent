"""Phase 3 tests for PostgreSQL runtime state machine and step-level checkpoint resume."""
from __future__ import annotations

from dataclasses import replace

import pytest

from backend.agent.context_builder import ExecutionPrincipal
from backend.agent.contracts import AgentCommand, AgentRunSnapshot
from backend.agent.decision import AskDecision, FinalDecision, ToolCall
from backend.agent.persistence import InvalidTransition, VersionConflict
from backend.agent.runtime import AgentRuntime
from backend.agent.skills.catalog import SkillCatalog
from backend.agent.tools.executor import ToolExecutor
from backend.agent.tools.handlers import BoundFitnessReads
from backend.agent.tools.registry import SPECS
from backend.agent.unified_coach import UnifiedCoachWorkflow
from backend.application.ports.agent_decision_gateway import AgentDecisionResult
from backend.infrastructure.agent_runtime.postgres_checkpoint_store import (
    PostgresCheckpointStore,
)
from backend.infrastructure.agent_runtime.postgres_run_repository import (
    PostgresRunRepository,
)
from backend.infrastructure.repositories.file_fitness_repository import (
    FileFitnessRepository,
)


class _ScriptedGateway:
    model = "offline"

    def __init__(self, decisions, *, crash_on_call: int | None = None):
        self._seq = iter(decisions)
        self._crash_on_call = crash_on_call
        self._calls = 0
        self.requests = []

    def decide(self, request):
        self._calls += 1
        self.requests.append(request)
        if self._crash_on_call is not None and self._calls == self._crash_on_call:
            raise _SimulatedInterrupt("network drop mid-turn")
        return AgentDecisionResult(next(self._seq), self.model, {"total_tokens": 12})


class _SimulatedInterrupt(RuntimeError):
    retryable = False


def test_postgres_run_repository_optimistic_lock_and_null_user_id(pg_db):
    repo = PostgresRunRepository(pg_db)
    store = PostgresCheckpointStore(repo)

    snap = repo.create(AgentRunSnapshot("run-null", "req-null", None, "chat", "accepted"))
    running = repo.update(replace(snap, status="running"), "RUN_STARTED")
    with pytest.raises(VersionConflict):
        repo.update(replace(snap, status="failed"), "RUN_FAILED")

    c1 = store.save("run-null", None, "round_1", {"completed": True, "attempt": 1}, step_index=1)
    assert c1.version == 1
    c2 = store.save("run-null", None, "round_1", {"completed": True, "attempt": 2}, step_index=1)
    assert c2.version == 2
    assert store.latest("run-null", None).state == {"completed": True, "attempt": 2}
    assert len(store.list_for_run("run-null", None)) == 1

    recoverable = repo.list_recoverable()
    assert [r.run_id for r in recoverable] == ["run-null"]

    repo.update(replace(running, status="succeeded"), "RUN_SUCCEEDED")
    with pytest.raises(InvalidTransition):
        store.save("run-null", None, "round_2", {"completed": True}, step_index=2)


def test_step_checkpoint_resume_reuses_valid_tool_and_recomputes_invalidated_domain(pg_db):
    repo = PostgresRunRepository(pg_db)
    store = PostgresCheckpointStore(repo)
    runtime = AgentRuntime(repository=repo, checkpoint_store=store)

    training_calls = {"count": 0}
    diet_calls = {"count": 0}
    dep_versions = {"profile": "v1", "training": "v1", "diet": "v1"}

    def training_calc(args, ctx):
        training_calls["count"] += 1
        return {"sets": 3, "reps": 10, "training_rev": dep_versions["training"]}

    def nutrition_calc(args, ctx):
        diet_calls["count"] += 1
        return {"target_kcal": 2200, "diet_rev": dep_versions["diet"]}

    calc_spec = SPECS["fitness.calculate"]
    # Build two specs mapped into private domains cleanly by using fitness.query + fitness.calculate
    training_spec = replace(calc_spec, handler=training_calc, required_domains=lambda args: frozenset({"training"}))
    query_spec = replace(SPECS["fitness.query"], handler=nutrition_calc, required_domains=lambda args: frozenset({"diet"}))

    def make_executor():
        principal = ExecutionPrincipal("u-resume", authorized_domains=frozenset({"training", "diet"}))
        return ToolExecutor(
            principal=principal,
            reads=BoundFitnessReads(FileFitnessRepository(), "u-resume"),
            catalog=SkillCatalog(),
            retriever=lambda *a, **k: [],
            specs={training_spec.name: training_spec, query_spec.name: query_spec},
            authorize=lambda p: p.authorized_domains,
            language="en-US",
        )

    cmd = AgentCommand("chat", "Adjust my plan and diet", "u-resume", language="en-US")

    # Initial run executes two tool calls and crashes on decision #3
    wf1 = UnifiedCoachWorkflow(
        _ScriptedGateway(
            [
                ToolCall(call_id="call_train", tool="fitness.calculate", arguments={"operation": "validate_training", "exercises": [{"name": "pushup", "sets": 3, "reps": 10, "rest_seconds": 60}]}),
                ToolCall(call_id="call_diet", tool="fitness.query", arguments={"domain": "diet", "fields": ["calories"], "start_date": "2026-01-01", "end_date": "2026-01-07"}),
                AskDecision(question="unreachable"),
            ],
            crash_on_call=3,
        ),
        make_executor(),
        dependency_version_provider=lambda d: dep_versions[d],
    )

    with pytest.raises(_SimulatedInterrupt) as raised:
        runtime.execute_sync(cmd, wf1)
    failed_run_id = raised.value.run_id
    assert training_calls["count"] == 1
    assert diet_calls["count"] == 1

    latest = store.latest(failed_run_id, "u-resume")
    assert latest is not None
    assert latest.name == "round_2"
    assert latest.state["step_index"] == 2

    # Resume #1: same dependency versions -> ZERO tool re-executions, input/output guards still run
    wf2 = UnifiedCoachWorkflow(
        _ScriptedGateway([AskDecision(question="Which equipment do you prefer for next week?")]),
        make_executor(),
        dependency_version_provider=lambda d: dep_versions[d],
    )
    resumed_cached = runtime.resume_sync(failed_run_id, cmd, wf2)
    assert resumed_cached.status == "succeeded"
    assert training_calls["count"] == 1
    assert diet_calls["count"] == 1
    events_cached = [e.event_type for e in repo.events(resumed_cached.run_id, "u-resume")]
    assert "RUN_RESUMED" in events_cached
    assert events_cached.count("SAFETY_DECIDED") == 2  # input_guard + output_guard

    # Resume #2: bump ONLY training dependency -> training tool recomputes (+1), diet remains cached!
    dep_versions["training"] = "v2"
    wf3 = UnifiedCoachWorkflow(
        _ScriptedGateway([AskDecision(question="Confirm updated training plan?")]),
        make_executor(),
        dependency_version_provider=lambda d: dep_versions[d],
    )
    resumed_partial = runtime.resume_sync(failed_run_id, cmd, wf3)
    assert resumed_partial.status == "succeeded"
    assert training_calls["count"] == 2
    assert diet_calls["count"] == 1


def test_checkpoint_resume_rejects_cross_user_or_policy_mismatch(pg_db):
    repo = PostgresRunRepository(pg_db)
    store = PostgresCheckpointStore(repo)
    runtime = AgentRuntime(repository=repo, checkpoint_store=store)

    run = repo.create(AgentRunSnapshot("r-sec", "req-sec", "owner-a", "chat", "accepted"))
    repo.update(replace(run, status="running"), "RUN_STARTED")
    store.save(
        "r-sec",
        "owner-a",
        "round_1",
        {
            "schema_version": 2,
            "stage": "tool_round",
            "step_index": 1,
            "principal_owner_id": "owner-a",
            "authorized_domains": ["profile"],
            "policy_version": "other-policy-v99",
            "completed_steps": ["input_guard"],
            "dependency_versions": {},
            "cached_tool_calls": [],
        },
        step_index=1,
    )

    principal = ExecutionPrincipal("owner-a", authorized_domains=frozenset({"profile"}))
    ex = ToolExecutor(
        principal=principal,
        reads=BoundFitnessReads(FileFitnessRepository(), "owner-a"),
        catalog=SkillCatalog(),
        retriever=lambda *a, **k: [],
        authorize=lambda p: p.authorized_domains,
    )
    wf = UnifiedCoachWorkflow(_ScriptedGateway([FinalDecision(body="unused")]), ex)

    # Cross-user resume fails lookup immediately
    with pytest.raises(KeyError):
        runtime.resume_sync("r-sec", AgentCommand("chat", "hi", "attacker"), wf)

    # Policy mismatch raises PermissionError inside workflow
    with pytest.raises(PermissionError, match="CHECKPOINT_POLICY_MISMATCH"):
        runtime.resume_sync("r-sec", AgentCommand("chat", "hi", "owner-a"), wf)
