"""Confirmation is one transaction, and the head moves by compare-and-swap.

The tests here are about *what a failure leaves behind*, not only about the happy
path. A confirmation touches five things -- history, head, task state, receipt and
the candidate's own record -- and every one of them has a way of being written
without the others. So each stage is made to fail in turn, and the assertion is
always the same: nothing moved.

The race test uses two real processes because the guard is a SQL statement, not a
lock. A single-process test with threads would pass even if the guard were
missing, since the repository serialises writers in-process anyway.
"""
from __future__ import annotations

import multiprocessing
import os
from datetime import datetime, timedelta, timezone

import pytest

from backend.application.ports.plan_repository import StoredPlan, legacy_head
from backend.domain.errors import ApplicationError
from backend.domain.plan_adjustment import CandidateBundle, CandidateVerdict, Patch
from backend.infrastructure.repositories.sqlite_plan_adjustment_repository import (
    SQLitePlanAdjustmentRepository,
)
from backend.infrastructure.repositories.sqlite_plan_repository import (
    SQLitePlanRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS

NOW = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)

BASE_DOCUMENT = {
    "diet_plan": {
        "meals": ["燕麦粥与鸡蛋"],
        "daily_calorie_target": 1800,
        "daily_protein_target": 120,
    },
    "workout_plan": {
        "days": [{"day": "周一", "exercises": [{"name": "深蹲"}], "duration_min": 40}],
        "weekly_training_days": 3,
        "rest_days": ["周日"],
    },
    "validation": {"passed": True, "warnings": [], "violations": [], "repair_suggestions": []},
}

CANDIDATE_DOCUMENT = {
    **BASE_DOCUMENT,
    "workout_plan": {
        **BASE_DOCUMENT["workout_plan"],
        "days": [{"day": "周一", "exercises": [{"name": "深蹲"}], "duration_min": 55}],
    },
}

CONSTRAINTS = {
    "allergies_or_restrictions": [],
    "action_restrictions": [],
    "available_equipment": ["barbell"],
}


def _database(tmp_path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    return database


def _plans(database, *, now=NOW) -> SQLitePlanRepository:
    counter = {"n": 0}

    def next_id():
        counter["n"] += 1
        return f"new{counter['n']:04d}"

    return SQLitePlanRepository(database, clock=lambda: now, ids=next_id)


def _stored(plan_id="p1", *, document=None, when=NOW, kind="deterministic",
            based_on=None) -> StoredPlan:
    return StoredPlan(plan_id=plan_id, activated_at=when, kind=kind,
                      based_on_plan_id=based_on, plan=document or BASE_DOCUMENT)


def _patch(**overrides) -> Patch:
    values = dict(domain="training", path=("workout_plan", "days", 0),
                  old_value={"day": "周一", "exercises": [{"name": "深蹲"}], "duration_min": 40},
                  new_value={"day": "周一", "exercises": [{"name": "深蹲"}], "duration_min": 55},
                  reason="延长训练时间", evidence_refs=())
    values.update(overrides)
    return Patch(**values)


_TASK_SEQUENCE = {"n": 0}


def _counter():
    def next_id():
        _TASK_SEQUENCE["n"] += 1
        return f"task-{_TASK_SEQUENCE['n']:04d}"

    return next_id


def _awaiting_confirmation(database, *, owner="alice", base_plan_id="p1", head=1,
                           document=None, change_domains=frozenset({"training"}),
                           created_at=NOW):
    """A task whose candidate passed and is waiting for the user."""
    adjustments = SQLitePlanAdjustmentRepository(
        database, clock=lambda: created_at, ids=_counter())
    suffix = f"{_TASK_SEQUENCE['n'] + 1}"
    created = adjustments.create_task(
        owner, base_plan_id=base_plan_id, base_head_revision=head,
        read_domains=frozenset({"training", "diet"}), change_domains=change_domains,
        constraints=dict(CONSTRAINTS), key=f"create-{owner}-{suffix}")
    generating = adjustments.transition(owner, created.task_id, created.version,
                                        "generating", key=f"go-{created.task_id}")
    bundle = CandidateBundle(patches=(_patch(),))
    verdict = CandidateVerdict(candidate_id="candidate-1", digest=bundle.digest(),
                               passed=True, dependency_digest="d" * 64)
    submitted = adjustments.submit_bundle(
        owner, created.task_id, generating.version, f"submit-{created.task_id}",
        bundle, verdict, candidate=document or CANDIDATE_DOCUMENT)
    assert submitted.state == "awaiting_confirmation"
    return created.task_id, submitted, verdict.digest


def _verified(context) -> dict:
    """A verifier that accepts: it must still produce the stored document."""
    return dict(context.candidate_plan)


def _activation(plans, task_id, submitted, digest, *, key="confirm-1", head=1):
    return plans.activate("alice", task_id=task_id, expected_version=submitted.version,
                          expected_head_revision=head, candidate_digest=digest,
                          operation_key=key, verify=_verified)


# --------------------------------------------------------------------- the path


def test_a_confirmation_writes_one_plan_and_advances_the_head(tmp_path):
    database = _database(tmp_path)
    plans = _plans(database)
    plans.save("alice", _stored())
    task_id, submitted, digest = _awaiting_confirmation(database)

    receipt = _activation(plans, task_id, submitted, digest)

    assert receipt.head_revision == 2
    assert receipt.plan_id.startswith("plan-")
    assert receipt.kind == "agent_adjusted"
    assert receipt.based_on_plan_id == "p1"
    head = plans.current_head("alice")
    assert head is not None and head.revision == 2 and head.plan_id == receipt.plan_id
    stored = plans.get("alice", receipt.plan_id)
    assert stored is not None and stored.plan_id == receipt.plan_id


def test_the_task_is_marked_activated(tmp_path):
    database = _database(tmp_path)
    plans = _plans(database)
    plans.save("alice", _stored())
    task_id, submitted, digest = _awaiting_confirmation(database)

    _activation(plans, task_id, submitted, digest)

    adjustments = SQLitePlanAdjustmentRepository(database, clock=lambda: NOW)
    snapshot = adjustments.get("alice", task_id)
    assert snapshot.state == "activated"
    assert snapshot.version == submitted.version + 1


def test_the_verifier_receives_the_bytes_about_to_be_written(tmp_path):
    database = _database(tmp_path)
    plans = _plans(database)
    plans.save("alice", _stored())
    task_id, submitted, digest = _awaiting_confirmation(database)
    seen = {}

    def verify(context):
        seen["document"] = context.candidate_plan
        seen["head"] = context.head.revision
        seen["base"] = context.base_plan.plan_id
        seen["constraints"] = context.constraints
        return dict(context.candidate_plan)

    plans.activate("alice", task_id=task_id, expected_version=submitted.version,
                   expected_head_revision=1, candidate_digest=digest,
                   operation_key="confirm-1", verify=verify)

    assert seen["document"] == CANDIDATE_DOCUMENT
    assert seen["head"] == 1
    assert seen["base"] == "p1"
    assert seen["constraints"] == CONSTRAINTS


def test_a_verifier_that_produces_nothing_is_a_refusal(tmp_path):
    database = _database(tmp_path)
    plans = _plans(database)
    plans.save("alice", _stored())
    task_id, submitted, digest = _awaiting_confirmation(database)

    with pytest.raises(ApplicationError) as raised:
        plans.activate("alice", task_id=task_id, expected_version=submitted.version,
                       expected_head_revision=1, candidate_digest=digest,
                       operation_key="confirm-1", verify=lambda context: {})

    assert raised.value.code == "CANDIDATE_DOCUMENT_MISSING"
    assert len(plans.list("alice")) == 1


# ------------------------------------------------------------------ the replay


def test_a_replayed_confirmation_returns_the_same_plan(tmp_path):
    database = _database(tmp_path)
    plans = _plans(database)
    plans.save("alice", _stored())
    task_id, submitted, digest = _awaiting_confirmation(database)

    first = _activation(plans, task_id, submitted, digest)
    second = _activation(plans, task_id, submitted, digest)

    assert second.plan_id == first.plan_id
    assert second.replayed is True
    assert len(plans.list("alice")) == 2
    assert plans.current_head("alice").revision == 2


def test_the_same_key_with_a_different_payload_is_a_conflict(tmp_path):
    database = _database(tmp_path)
    plans = _plans(database)
    plans.save("alice", _stored())
    task_id, submitted, digest = _awaiting_confirmation(database)
    _activation(plans, task_id, submitted, digest)

    with pytest.raises(ApplicationError) as raised:
        plans.activate("alice", task_id=task_id, expected_version=submitted.version,
                       expected_head_revision=2, candidate_digest=digest,
                       operation_key="confirm-1", verify=_verified)

    assert raised.value.code == "IDEMPOTENCY_CONFLICT"


# ------------------------------------------------------------- the stale base


def test_a_candidate_reviewed_against_an_old_head_is_refused(tmp_path):
    database = _database(tmp_path)
    plans = _plans(database)
    plans.save("alice", _stored())
    first_task, first_submission, first_digest = _awaiting_confirmation(database)
    second_task, second_submission, second_digest = _awaiting_confirmation(
        database, created_at=NOW + timedelta(seconds=1))

    _activation(plans, first_task, first_submission, first_digest)

    with pytest.raises(ApplicationError) as raised:
        _activation(plans, second_task, second_submission, second_digest,
                    key="confirm-2")

    assert raised.value.code == "PLAN_BASE_STALE"
    assert len(plans.list("alice")) == 2


def test_a_confirmation_with_the_wrong_digest_is_refused(tmp_path):
    database = _database(tmp_path)
    plans = _plans(database)
    plans.save("alice", _stored())
    task_id, submitted, _digest = _awaiting_confirmation(database)

    with pytest.raises(ApplicationError) as raised:
        _activation(plans, task_id, submitted, "f" * 64)

    assert raised.value.code == "CANDIDATE_DIGEST_MISMATCH"


def test_an_expired_candidate_is_refused_before_the_plan_is_written(tmp_path):
    database = _database(tmp_path)
    plans = _plans(database, now=NOW + timedelta(hours=2))
    plans.save("alice", _stored())
    task_id, submitted, digest = _awaiting_confirmation(database)

    with pytest.raises(ApplicationError) as raised:
        _activation(plans, task_id, submitted, digest)

    assert raised.value.code == "CANDIDATE_EXPIRED"
    assert len(plans.list("alice")) == 1


def test_another_owners_task_is_not_found(tmp_path):
    database = _database(tmp_path)
    plans = _plans(database)
    plans.save("alice", _stored())
    task_id, submitted, digest = _awaiting_confirmation(database)

    with pytest.raises(ApplicationError) as raised:
        plans.activate("bob", task_id=task_id, expected_version=submitted.version,
                       expected_head_revision=1, candidate_digest=digest,
                       operation_key="confirm-1", verify=_verified)

    assert raised.value.code == "TASK_NOT_FOUND"


def test_a_candidate_that_changed_an_ungranted_domain_is_refused(tmp_path):
    database = _database(tmp_path)
    plans = _plans(database)
    plans.save("alice", _stored())
    changed_diet = {**CANDIDATE_DOCUMENT,
                    "diet_plan": {**BASE_DOCUMENT["diet_plan"], "daily_calorie_target": 1500}}
    task_id, submitted, digest = _awaiting_confirmation(database, document=changed_diet)

    with pytest.raises(ApplicationError) as raised:
        _activation(plans, task_id, submitted, digest)

    assert raised.value.code == "CHANGE_DOMAIN_NOT_AUTHORIZED"
    assert len(plans.list("alice")) == 1


# -------------------------------------------------------------- the two writers


def _spawn_activate(path, task_id, version, head, digest, barrier, results, now):
    from backend.infrastructure.repositories.sqlite_plan_repository import (
        SQLitePlanRepository,
    )
    from backend.infrastructure.sqlite.database import SQLiteDatabase

    # The clock has to cross the process boundary. The candidate was submitted at
    # a fixed instant and expires thirty minutes later, so a child reading the wall
    # clock reports CANDIDATE_EXPIRED long before it reaches the guard this test is
    # about -- and the assertion then fails for a reason that has nothing to do
    # with two writers. ``now`` is a datetime rather than a callable because only
    # the former survives ``spawn``.
    repository = SQLitePlanRepository(SQLiteDatabase(path), clock=lambda: now)
    barrier.wait(timeout=30)
    try:
        receipt = repository.activate(
            "alice", task_id=task_id, expected_version=version,
            expected_head_revision=head, candidate_digest=digest,
            operation_key=f"confirm-{os.getpid()}", verify=lambda context: dict(context.candidate_plan))
        results.put(("won", receipt.plan_id, receipt.head_revision))
    except Exception as error:  # noqa: BLE001 - the child reports the failure verbatim
        results.put(("lost", getattr(error, "code", type(error).__name__)))
    finally:
        results.close()


def test_two_processes_cannot_both_confirm_the_same_head(tmp_path):
    database = _database(tmp_path)
    plans = _plans(database)
    plans.save("alice", _stored())
    task_id, submitted, digest = _awaiting_confirmation(database)
    path = str(database.path)

    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = [context.Process(target=_spawn_activate,
                                 args=(path, task_id, submitted.version, 1, digest,
                                       barrier, results, NOW))
                 for _ in range(2)]
    outcomes = []
    try:
        for process in processes:
            process.start()
        for _ in processes:
            outcomes.append(results.get(timeout=40))
        for process in processes:
            process.join(timeout=20)
    finally:
        for process in processes:
            if process.pid and process.is_alive():
                process.terminate()
            if process.pid:
                process.join(timeout=5)
                process.close()
        results.close()

    winners = [outcome for outcome in outcomes if outcome[0] == "won"]
    losers = [outcome for outcome in outcomes if outcome[0] == "lost"]
    assert len(winners) == 1, outcomes
    assert len(losers) == 1, outcomes
    # The loser is refused by a statement, not by a lock: both processes hold the
    # same task version, so the second ``UPDATE ... WHERE version`` matches no row.
    # The head guard is the other half of the same story and is covered by
    # ``test_a_candidate_reviewed_against_an_old_head_is_refused``, which is where
    # two *different* tasks compete for one head.
    assert losers[0][1] == "TASK_VERSION_CONFLICT", outcomes
    # One head version was spent, and the base plan is byte-for-byte what it was.
    assert winners[0][2] == 2
    assert plans.current_head("alice").revision == 2
    assert len(plans.list("alice")) == 2
    assert plans.get("alice", "p1").model_dump() == _stored().model_dump()


# ------------------------------------------------------------- the fault points


def _fail_after(original):
    def wrapper(*args, **kwargs):
        result = original(*args, **kwargs)
        raise RuntimeError("injected")
    return wrapper


@pytest.mark.parametrize("stage", ["insert_plan", "advance_head", "receipt"])
def test_a_failure_at_any_stage_rolls_back_everything(tmp_path, monkeypatch, stage):
    database = _database(tmp_path)
    plans = _plans(database)
    plans.save("alice", _stored())
    task_id, submitted, digest = _awaiting_confirmation(database)
    before = plans.list("alice")

    target = {"insert_plan": "_insert_plan", "advance_head": "_advance_head",
              "receipt": "_store_activation_receipt"}[stage]
    monkeypatch.setattr(SQLitePlanRepository, target,
                        _fail_after(getattr(SQLitePlanRepository, target)))

    with pytest.raises(RuntimeError):
        _activation(plans, task_id, submitted, digest)

    assert plans.list("alice") == before
    assert plans.current_head("alice").revision == 1
    adjustments = SQLitePlanAdjustmentRepository(database, clock=lambda: NOW)
    snapshot = adjustments.get("alice", task_id)
    assert snapshot.state == "awaiting_confirmation"
    assert snapshot.version == submitted.version
    with database.connection() as connection:
        assert connection.execute(
            "SELECT COUNT(*) AS n FROM plan_activation_receipts").fetchone()["n"] == 0


# ----------------------------------------------------------------- the history


def test_history_refuses_a_second_document_under_one_id(tmp_path):
    database = _database(tmp_path)
    plans = _plans(database)
    plans.save("alice", _stored())

    with pytest.raises(ApplicationError) as raised:
        plans.save("alice", _stored(document={**BASE_DOCUMENT, "trace": {"changed": True}}))

    assert raised.value.code == "PLAN_HISTORY_CONFLICT"
    assert plans.get("alice", "p1").plan.model_dump() == _stored().plan.model_dump()


def test_saving_the_same_plan_twice_does_not_spend_a_head_version(tmp_path):
    database = _database(tmp_path)
    plans = _plans(database)
    plans.save("alice", _stored())

    plans.save("alice", _stored())

    assert plans.current_head("alice").revision == 1
    assert len(plans.list("alice")) == 1


def test_the_legacy_head_is_the_newest_activation(tmp_path):
    earlier = NOW - timedelta(days=1)
    plans = [_stored("plan-aaaaaaaa", when=earlier), _stored("plan-bbbbbbbb", when=NOW)]

    head = legacy_head(plans)

    assert head.plan_id == "plan-bbbbbbbb"
    assert head.revision == 2


def test_ties_are_broken_by_plan_id_so_directory_order_does_not_decide(tmp_path):
    head = legacy_head([_stored("plan-ffffffff"), _stored("plan-aaaaaaaa")])

    assert head.plan_id == "plan-ffffffff"


# --------------------------------------------------------------- the deletion


def test_deletion_removes_only_the_owners_history(tmp_path):
    database = _database(tmp_path)
    plans = _plans(database)
    plans.save("alice", _stored())
    plans.save("bob", _stored())

    counts = plans.delete_user_data("alice")

    assert counts["plans"] == 1 and counts["plan_heads"] == 1
    assert plans.list("alice") == [] and plans.current_head("alice") is None
    assert [plan.plan_id for plan in plans.list("bob")] == ["p1"]
    assert plans.current_head("bob").revision == 1


def test_a_confirmation_after_deletion_cannot_resurrect_a_plan(tmp_path):
    """The task row is the thing that makes resurrection impossible.

    A deletion that removed the plans but left the task would let a confirmation
    that was already in flight write the plan back. Deleting the task first is what
    turns that write into ``TASK_NOT_FOUND`` instead of a new history row.
    """
    database = _database(tmp_path)
    plans = _plans(database)
    plans.save("alice", _stored())
    task_id, submitted, digest = _awaiting_confirmation(database)
    adjustments = SQLitePlanAdjustmentRepository(database, clock=lambda: NOW)

    plans.delete_user_data("alice")
    adjustments.delete_user_data("alice")

    with pytest.raises(ApplicationError) as raised:
        _activation(plans, task_id, submitted, digest)
    assert raised.value.code == "TASK_NOT_FOUND"
    assert plans.list("alice") == []
    assert plans.current_head("alice") is None
