"""Evidence for constrained plan tasks, replayed through the public API.

Two kinds of assertion live here, and they are deliberately kept apart.

*The contract.* A suite that needs the plan capability must report ``unsupported``
rather than ``passed`` when the deployment does not have it, and the observation
whitelist must accept only bounded task metadata -- a state, a count, a revision,
a digest -- while refusing a plan document, a constraint value or an arbitrary
JSON path. A scenario may not score on prose either: "两个部分都已通过校验" is a
sentence, not a validator verdict.

*The replay.* Scenarios run in network-blocked isolated workers and are scored on
persisted facts: how many rounds were claimed, which candidate survived, which head
was written, whether the domain that already passed was left byte-identical. None
of that is read from what the model said.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from backend.agent.context_builder import ExecutionPrincipal
from backend.task_evaluation.contracts import Scenario, Step, Suite
from backend.task_evaluation.runner import (
    CaseError,
    CaseResult,
    _observe_response,
    execute_scenario,
    run_isolated_scenario,
    to_run_record,
)
from backend.task_evaluation.scorers import score_state

SUITE_PATH = Path(__file__).parents[2] / "task_evaluation/scenarios/plan_adjustment.json"

DECLARED = (
    "plan-task-training-only",
    "plan-task-diet-only",
    "plan-task-cross-domain-refused",
    "plan-task-read-only-no-grant",
    "plan-task-first-candidate-passes",
    "plan-task-two-rounds",
    "plan-task-rounds-exhausted",
    "plan-task-goal-conflict-asks",
    "plan-task-stale-head-refused",
    "plan-task-confirm-replay",
    "plan-task-same-round-recovery",
    "plan-task-unauthorized-and-forged-confirm",
)


def suite() -> Suite:
    return Suite.model_validate_json(SUITE_PATH.read_text(encoding="utf-8"))


# -- the declaration -----------------------------------------------------
def test_the_suite_declares_the_twelve_named_scenarios():
    cases = suite().scenarios
    assert tuple(case.id for case in cases) == DECLARED
    assert all(case.requires == ["plan_adjustment"] for case in cases)


def test_a_deployment_without_the_capability_reports_unsupported():
    """Not "passed": a suite that needs a capability the deployment lacks has not
    measured anything, and reporting success would be the lie this status exists
    to prevent."""
    scenario = suite().scenarios[0]

    class Client:
        def request(self, *args, **kwargs):  # pragma: no cover - never reached
            raise AssertionError("An unsupported suite must not call the API")

    result = execute_scenario(scenario, Client(), headers_factory=lambda _: {})
    assert result.status == "unsupported"
    assert result.failures == ("requires",)


def test_a_scenario_may_not_score_on_prose():
    with pytest.raises(ValueError):
        score_state({"answer_markdown": "已完成"}, {"answer_markdown": "已完成"})
    # A bounded fact still scores normally.
    assert score_state({"plan_rounds": 2}, {"plan_rounds": 2}).passed


# -- what a report may observe -------------------------------------------
@pytest.mark.parametrize("path,key", [
    ("data.state", "state"),
    ("data.task.state", "state"),
    ("data.task.repair_rounds", "rounds"),
    ("data.task.rounds_remaining", "remaining"),
    ("data.task.failed_domains", "failed"),
    ("data.task.violations.length", "violations"),
    ("data.plan.head_revision", "head"),
    ("data.replayed", "replayed"),
    ("data.task.candidate.digest", "digest"),
])
def test_bounded_task_metadata_can_be_observed(path, key):
    payload = {"data": {"state": "repairing", "task": {
        "state": "repairing", "repair_rounds": 2, "rounds_remaining": 0,
        "failed_domains": ["diet"], "violations": [{"code": "CALORIE_TOO_LOW"}],
        "candidate": {"digest": "a" * 64}},
        "plan": {"head_revision": 3}, "replayed": True}}
    observed = _observe_response(payload, {key: path})
    assert set(observed) == {key}


@pytest.mark.parametrize("path", [
    "data.instructions",
    "data.answer",
    "data.answer_markdown",
    "data.task.candidate",
    "data.task.constraints.available_equipment",
    "data.task.violations.0.code",
    "data.plan.workout_plan.days.0.focus",
])
def test_a_plan_document_or_constraint_value_cannot_be_observed(path):
    payload = {"data": {
        "instructions": "把训练强度调低一点",
        "answer": "已完成", "answer_markdown": "已完成",
        "task": {"candidate": {"digest": "a" * 64},
                 "constraints": {"available_equipment": ["barbell"]},
                 "violations": [{"code": "CALORIE_TOO_LOW"}]},
        "plan": {"workout_plan": {"days": [{"focus": "下肢"}]}},
    }}
    with pytest.raises(CaseError):
        _observe_response(payload, {"leak": path})


def test_a_domain_list_must_be_a_sorted_closed_enum():
    payload = {"data": {"task": {"failed_domains": ["diet", "training"]}}}
    assert _observe_response(payload, {"failed": "data.task.failed_domains"}) == {
        "failed": ["diet", "training"]}
    for value in (["training", "diet"], ["diet", "diet"], ["diet", "sleep"]):
        with pytest.raises(CaseError):
            _observe_response({"data": {"task": {"failed_domains": value}}},
                              {"failed": "data.task.failed_domains"})


# -- what the database reports -------------------------------------------
def _plan_database(path, *, candidates, rounds=(1,), state="awaiting_confirmation"):
    """A minimal plan-task store, so the observation can be read without the app."""
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE plan_adjustment_sessions (task_id TEXT, user_id TEXT, state TEXT,"
            " version INTEGER, repair_rounds INTEGER, base_plan_id TEXT, candidate_id TEXT,"
            " created_at TEXT)")
        connection.execute(
            "CREATE TABLE plan_candidate_submissions (task_id TEXT, round_index INTEGER,"
            " candidate_json TEXT)")
        connection.execute(
            "CREATE TABLE plan_repair_rounds (task_id TEXT, round_index INTEGER)")
        connection.execute(
            "CREATE TABLE plan_activation_receipts (user_id TEXT, operation_key TEXT)")
        connection.execute("CREATE TABLE plan_heads (user_id TEXT, plan_id TEXT, revision INTEGER)")
        connection.execute("CREATE TABLE plans (user_id TEXT, plan_id TEXT, plan_json TEXT)")
        connection.execute("INSERT INTO plan_adjustment_sessions VALUES (?,?,?,?,?,?,?,?)",
                           ("task-1", "owner", state, 7, len(rounds), "plan-00000001",
                            "candidate", "2026-01-01"))
        for index in rounds:
            connection.execute("INSERT INTO plan_repair_rounds VALUES (?,?)", ("task-1", index))
        for round_index, document in candidates:
            connection.execute("INSERT INTO plan_candidate_submissions VALUES (?,?,?)",
                               ("task-1", round_index, None if document is None
                                else json.dumps(document, ensure_ascii=False)))
        connection.execute("INSERT INTO plan_heads VALUES (?,?,?)", ("owner", "plan-00000001", 3))
        connection.execute("INSERT INTO plans VALUES (?,?,?)", (
            "owner", "plan-00000001",
            json.dumps({"workout_plan": {"days": ["original"], "weekly_training_days": 4},
                        "diet_plan": {"meals": ["花生燕麦粥"], "daily_calorie_target": 1000}})))


def test_the_domains_that_did_not_change_are_compared_deeply(tmp_path):
    """Two candidates, one domain byte-identical.

    The comparison is against the stored documents, not against the digest the
    same code wrote: a report that trusted the digest would agree with a bug.
    """
    from backend.task_evaluation.observation import observe_database

    database = tmp_path / "plan.sqlite3"
    _plan_database(database, candidates=[
        (1, {"workout_plan": {"days": ["fixed"], "weekly_training_days": 4},
             "diet_plan": {"meals": ["花生酱"], "daily_calorie_target": 1000}}),
        (2, {"workout_plan": {"days": ["fixed"], "weekly_training_days": 4},
             "diet_plan": {"meals": ["燕麦粥"], "daily_calorie_target": 1000}}),
    ])
    observed = observe_database(database, actors={"primary": "owner"})

    assert observed["plan_domains_unchanged"] == ["training"]
    # The target never moved, even though the plan's own target is below the floor.
    assert observed["plan_targets_unchanged"] is True
    assert observed["plan_round_indices"] == [1]
    assert observed["plan_head_revision"] == 3
    assert observed["plan_history"] == 1
    # And nothing the observation carries quotes the plan or the constraint values.
    assert "花生" not in str(observed)
    assert "original" not in str(observed)


def test_a_moved_target_is_reported_as_moved(tmp_path):
    from backend.task_evaluation.observation import observe_database

    database = tmp_path / "plan.sqlite3"
    _plan_database(database, candidates=[
        (0, {"workout_plan": {"days": ["original"], "weekly_training_days": 4},
             "diet_plan": {"meals": ["燕麦粥"], "daily_calorie_target": 2000}}),
    ])
    observed = observe_database(database, actors={"primary": "owner"})

    assert observed["plan_targets_unchanged"] is False


def test_a_task_scoped_fact_is_absent_when_the_account_has_no_task(tmp_path):
    from backend.task_evaluation.observation import observe_database

    database = tmp_path / "plan.sqlite3"
    _plan_database(database, candidates=[])
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM plan_adjustment_sessions")
    observed = observe_database(database, actors={"primary": "owner"})

    assert observed["plan_tasks"] == 0
    # Not "false": with no task there is no answer, and a missing key fails a
    # scenario that expected one instead of quietly matching.
    assert "plan_domains_unchanged" not in observed
    assert "plan_targets_unchanged" not in observed


# -- the authorization spy -----------------------------------------------
class _Catalog:
    def verify_release(self):
        return None


class _Reads:
    owner_id = "alice"


def _counting_executor(authorized):
    from backend.task_evaluation.worker import _install_authorization_spy
    from backend.api import plan_adjustment as plan_adjustment_api

    counter = {"checks": 0, "denied": 0}
    original = plan_adjustment_api.ToolExecutor
    _install_authorization_spy(counter)
    try:
        return plan_adjustment_api.ToolExecutor(
            principal=ExecutionPrincipal("alice", authorized_domains=frozenset({"training"})),
            reads=_Reads(), catalog=_Catalog(),
            authorize=lambda principal: authorized,
            retriever=lambda *args, **kwargs: [], specs={}, session=None), counter
    finally:
        plan_adjustment_api.ToolExecutor = original


def test_the_authorization_spy_counts_checks_and_denials():
    """The claim is "every decision was re-authorized", so the count must be exact.

    A closed tool list is a static property of the code; this is the measurement
    that the loop actually consults it, and that a revoked scope ends the round
    instead of being reported as a refusal the model can talk its way past.
    """
    executor, counter = _counting_executor(frozenset({"training"}))
    executor.check_access()
    executor.check_access()
    assert counter == {"checks": 2, "denied": 0}

    revoked, revoked_counter = _counting_executor(frozenset())
    with pytest.raises(PermissionError):
        revoked.check_access()
    assert revoked_counter == {"checks": 1, "denied": 1}


# -- what a record carries -----------------------------------------------
def test_a_record_carries_plan_invariants_and_never_a_document():
    result = CaseResult("plan-task-x", 1, "passed", observed={
        "plan_rounds": 2, "plan_round_indices": [1, 2], "plan_head_revision": 3,
        "plan_domains_unchanged": ["training"], "plan_targets_unchanged": True,
        "plan_task_states": ["activated"], "gateway_attempts": 9,
        "plan_document": {"diet_plan": {"meals": ["花生燕麦粥"]}},
        "plan_constraints": {"allergies_or_restrictions": ["花生"]},
        "answer": "已完成",
    })

    record = to_run_record(result, mode="mock")

    assert record.details["plan_invariants"] == {
        "plan_rounds": 2, "plan_round_indices": [1, 2], "plan_head_revision": 3,
        "plan_domains_unchanged": ["training"], "plan_targets_unchanged": True,
        "plan_task_states": ["activated"],
    }
    assert "花生" not in str(record.details)


# -- the replay ----------------------------------------------------------
def _run(scenario_id: str):
    scenario = next(case for case in suite().scenarios if case.id == scenario_id)
    return scenario, run_isolated_scenario(scenario, deadline=time.monotonic() + 300)


@pytest.mark.parametrize("scenario_id", [
    "plan-task-training-only",
    "plan-task-read-only-no-grant",
    "plan-task-two-rounds",
    "plan-task-stale-head-refused",
])
def test_network_blocked_workers_replay_the_declared_scenarios(scenario_id):
    scenario, result = _run(scenario_id)

    assert result.status == "passed", (result.failures, result.observed)
    assert score_state(scenario.expected, result.observed).passed
    assert result.metrics["cleanup_status"] == "completed"
    # No record was created by a plan task: the task writes plans, not meals.
    assert result.observed["confirmed_meals"] == 0


def test_a_read_only_task_spends_no_model_call_and_writes_no_head():
    """The one scenario that must cost nothing, asserted as exactly nothing."""
    scenario, result = _run("plan-task-read-only-no-grant")

    assert result.status == "passed", (result.failures, result.observed)
    assert result.observed["gateway_attempts"] == 0
    assert result.observed["plan_authorize_checks"] == 0
    assert result.observed["plan_candidates"] == 0
    assert result.observed["plan_head_revision"] == 1
    assert result.observed["plan_history"] == 1


def test_the_two_round_scenario_never_rewrites_the_domain_that_passed():
    """The deep comparison, as measured by the run rather than asserted by hand."""
    _, result = _run("plan-task-two-rounds")

    assert result.status == "passed", (result.failures, result.observed)
    assert result.observed["plan_domains_unchanged"] == ["training"]
    assert result.observed["plan_round_indices"] == [1, 2]
    assert result.observed["plan_candidates"] == 3
    assert result.observed["plan_head_revision"] == 2
    assert result.observed["plan_history"] == 2
