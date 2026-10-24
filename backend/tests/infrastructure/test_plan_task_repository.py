"""Persistent plan tasks: one version, one grant, at most two repair rounds.

These tests drive a real SQLite file through the public repository methods. The
point is not that the SQL runs, but that a replayed request cannot spend a second
round, a stale version cannot overwrite a newer one, and a task that belongs to
somebody else looks exactly like a task that does not exist.
"""
from __future__ import annotations

import multiprocessing
from datetime import datetime, timedelta, timezone

import pytest

from backend.domain.errors import ApplicationError
from backend.application.ports.plan_adjustment_repository import (
    REPAIR_ROUND_LIMIT,
    TASK_STATES,
    TaskSnapshot,
)
from backend.domain.plan_adjustment import (
    CandidateBundle,
    CandidateVerdict,
    Patch,
    Violation,
)
from backend.infrastructure.repositories.sqlite_plan_adjustment_repository import (
    SQLitePlanAdjustmentRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def _repository(path, *, now=NOW, ids=None):
    database = SQLiteDatabase(path)
    run_migrations(database, RECORDS_MIGRATIONS)
    return SQLitePlanAdjustmentRepository(
        database,
        clock=lambda: now,
        ids=ids or _counter_ids(),
    )


def _counter_ids():
    seen = {"n": 0}

    def next_id():
        seen["n"] += 1
        return f"id-{seen['n']:04d}"

    return next_id


def _task(repo, key="create-1", owner="alice", **overrides):
    values = dict(base_plan_id="p1", base_head_revision=1,
                  read_domains=frozenset({"training"}),
                  change_domains=frozenset({"training"}),
                  constraints={}, key=key)
    values.update(overrides)
    return repo.create_task(owner, **values)


def _patch(**overrides):
    values = dict(domain="training", path=("workout_plan", "days", 0),
                  old_value={"day": "周一"}, new_value={"day": "周一", "intensity": "high"},
                  reason="提高强度", evidence_refs=())
    values.update(overrides)
    return Patch(**values)


def _verdict(passed=True, code="PATCH_STALE"):
    bundle_digest = "b" * 64
    return CandidateVerdict(
        candidate_id=bundle_digest[:32], digest=bundle_digest, passed=passed,
        failed_domains=() if passed else ("training",),
        violations=() if passed else (Violation(code=code, domain="training", path="workout_plan.days.0"),),
        dependency_digest="d" * 64,
    )


def test_same_create_operation_returns_same_task(tmp_path):
    repo = _repository(tmp_path / "plan.sqlite3")
    task = repo.create_task("alice", base_plan_id="p1", base_head_revision=1,
                            read_domains=frozenset({"training"}), change_domains=frozenset({"training"}),
                            constraints={}, key="create-1")
    replay = repo.create_task("alice", base_plan_id="p1", base_head_revision=1,
                              read_domains=frozenset({"training"}), change_domains=frozenset({"training"}),
                              constraints={}, key="create-1")

    assert task.task_id == replay.task_id
    assert task.version == replay.version
    assert replay.repair_rounds == 0


def test_same_key_with_a_different_payload_is_a_conflict(tmp_path):
    repo = _repository(tmp_path / "plan.sqlite3")
    _task(repo)
    with pytest.raises(ApplicationError, match="IDEMPOTENCY_CONFLICT"):
        _task(repo, base_plan_id="p2")


def test_unknown_and_foreign_task_share_one_not_found(tmp_path):
    repo = _repository(tmp_path / "plan.sqlite3")
    task = _task(repo)
    with pytest.raises(KeyError):
        repo.get("alice", "no-such-task")
    with pytest.raises(KeyError):
        repo.get("bob", task.task_id)


def test_snapshot_exposes_the_grant_and_the_initial_state(tmp_path):
    repo = _repository(tmp_path / "plan.sqlite3")
    task = _task(repo)

    assert task.state == "collecting"
    assert task.read_domains == frozenset({"training"})
    assert task.change_domains == frozenset({"training"})
    assert task.version == 1
    assert task.constraint_digest and len(task.constraint_digest) == 64
    assert task.expires_at == NOW + timedelta(days=30)
    assert task.candidate_expires_at is None


def test_stale_version_cannot_overwrite(tmp_path):
    repo = _repository(tmp_path / "plan.sqlite3")
    task = _task(repo)
    repo.grant("alice", task.task_id, 1, frozenset({"training"}), frozenset({"training"}), key="grant-1")

    with pytest.raises(ApplicationError, match="TASK_VERSION_CONFLICT"):
        repo.transition("alice", task.task_id, 1, "generating", key="stale")


def test_grant_replaces_permissions_and_bumps_the_version(tmp_path):
    repo = _repository(tmp_path / "plan.sqlite3")
    task = _task(repo)

    granted = repo.grant("alice", task.task_id, 1, frozenset({"training", "diet"}),
                         frozenset({"diet"}), key="grant-1")

    assert granted.version == 2
    assert granted.read_domains == frozenset({"training", "diet"})
    assert granted.change_domains == frozenset({"diet"})
    assert granted.state == "generating"


def test_change_grant_must_be_a_subset_of_the_read_grant(tmp_path):
    repo = _repository(tmp_path / "plan.sqlite3")
    task = _task(repo)
    with pytest.raises(ValueError):
        repo.grant("alice", task.task_id, 1, frozenset({"training"}), frozenset({"diet"}), key="grant-1")


def test_scope_cannot_widen_once_generation_started(tmp_path):
    repo = _repository(tmp_path / "plan.sqlite3")
    task = _task(repo)
    repo.grant("alice", task.task_id, 1, frozenset({"training"}), frozenset({"training"}), key="grant-1")

    with pytest.raises(ApplicationError, match="REQUIRES_NEW_TASK"):
        repo.grant("alice", task.task_id, 2, frozenset({"training", "diet"}), frozenset({"diet"}), key="grant-2")


def test_repeated_reservation_does_not_spend_a_second_round(tmp_path):
    repo = _repository(tmp_path / "plan.sqlite3")
    task = _task(repo)
    repo.grant("alice", task.task_id, 1, frozenset({"training"}), frozenset({"training"}), key="grant-1")

    first = repo.reserve_repair_round("alice", task.task_id, 2, "op-1", frozenset({"training"}))
    replay = repo.reserve_repair_round("alice", task.task_id, 2, "op-1", frozenset({"training"}))

    assert first.repair_rounds == 1
    assert replay.repair_rounds == 1
    assert replay.version == first.version
    assert replay.active_round_id == first.active_round_id


def test_an_unfinished_round_blocks_the_next_reservation(tmp_path):
    repo = _repository(tmp_path / "plan.sqlite3")
    task = _task(repo)
    repo.grant("alice", task.task_id, 1, frozenset({"training"}), frozenset({"training"}), key="grant-1")
    reserved = repo.reserve_repair_round("alice", task.task_id, 2, "op-1", frozenset({"training"}))

    with pytest.raises(ApplicationError, match="REPAIR_ROUND_ACTIVE"):
        repo.reserve_repair_round("alice", task.task_id, reserved.version, "op-2", frozenset({"training"}))


def test_only_two_repair_rounds_exist(tmp_path):
    repo = _repository(tmp_path / "plan.sqlite3")
    task = _task(repo)
    repo.grant("alice", task.task_id, 1, frozenset({"training"}), frozenset({"training"}), key="grant-1")
    version = 2
    for index in (1, 2):
        reserved = repo.reserve_repair_round("alice", task.task_id, version, f"op-{index}", frozenset({"training"}))
        version = reserved.version
        submitted = repo.submit_bundle("alice", task.task_id, version, f"sub-{index}",
                                       CandidateBundle(patches=(_patch(),)), _verdict(passed=False))
        version = submitted.version

    assert version and reserved.repair_rounds == REPAIR_ROUND_LIMIT
    with pytest.raises(ApplicationError, match="REPAIR_LIMIT"):
        repo.reserve_repair_round("alice", task.task_id, version, "op-3", frozenset({"training"}))


def test_first_candidate_does_not_spend_a_round(tmp_path):
    repo = _repository(tmp_path / "plan.sqlite3")
    task = _task(repo)
    repo.grant("alice", task.task_id, 1, frozenset({"training"}), frozenset({"training"}), key="grant-1")

    submitted = repo.submit_bundle("alice", task.task_id, 2, "submit-1",
                                   CandidateBundle(patches=(_patch(),)), _verdict(passed=True))

    assert submitted.repair_rounds == 0
    assert submitted.state == "awaiting_confirmation"
    assert submitted.candidate_id == "b" * 32
    assert submitted.candidate_digest == "b" * 64
    assert submitted.candidate_expires_at == NOW + timedelta(minutes=30)


def test_a_failed_verdict_consumes_the_round_and_asks_for_repair(tmp_path):
    repo = _repository(tmp_path / "plan.sqlite3")
    task = _task(repo)
    repo.grant("alice", task.task_id, 1, frozenset({"training"}), frozenset({"training"}), key="grant-1")

    submitted = repo.submit_bundle("alice", task.task_id, 2, "submit-1",
                                   CandidateBundle(patches=(_patch(),)), _verdict(passed=False))

    assert submitted.state == "repairing"
    assert submitted.candidate_id is None
    assert submitted.active_round_id is None
    assert submitted.repair_rounds == 0

    # The next attempt needs a reserved round, and reserving spends one.
    reserved = repo.reserve_repair_round("alice", task.task_id, submitted.version, "op-2",
                                         frozenset({"training"}))
    assert reserved.repair_rounds == 1
    assert reserved.active_round_id is not None


def test_submitting_without_a_reserved_round_is_refused(tmp_path):
    repo = _repository(tmp_path / "plan.sqlite3")
    task = _task(repo)
    repo.grant("alice", task.task_id, 1, frozenset({"training"}), frozenset({"training"}), key="grant-1")
    repo.submit_bundle("alice", task.task_id, 2, "submit-1",
                       CandidateBundle(patches=(_patch(),)), _verdict(passed=False))

    with pytest.raises(ApplicationError, match="REPAIR_ROUND_ACTIVE"):
        repo.submit_bundle("alice", task.task_id, 3, "submit-2",
                           CandidateBundle(patches=(_patch(),)), _verdict(passed=False))


def test_one_round_accepts_one_bundle(tmp_path):
    repo = _repository(tmp_path / "plan.sqlite3")
    task = _task(repo)
    repo.grant("alice", task.task_id, 1, frozenset({"training"}), frozenset({"training"}), key="grant-1")
    repo.submit_bundle("alice", task.task_id, 2, "submit-1",
                       CandidateBundle(patches=(_patch(),)), _verdict(passed=False))

    # Same key, different content: a replayed request may not swap the candidate.
    other = CandidateBundle(patches=(_patch(reason="另一个改动"),))
    with pytest.raises(ApplicationError, match="IDEMPOTENCY_CONFLICT"):
        repo.submit_bundle("alice", task.task_id, 3, "submit-1", other, _verdict(passed=False))
    # A fresh key cannot slip into the round that was already accepted.
    with pytest.raises(ApplicationError, match="REPAIR_ROUND_ACTIVE"):
        repo.submit_bundle("alice", task.task_id, 3, "submit-2", other, _verdict(passed=False))


def test_replay_is_matched_before_the_version_check(tmp_path):
    repo = _repository(tmp_path / "plan.sqlite3")
    task = _task(repo)
    repo.grant("alice", task.task_id, 1, frozenset({"training"}), frozenset({"training"}), key="grant-1")
    first = repo.transition("alice", task.task_id, 2, "awaiting_user_decision", key="state-1")

    # The same key with the version the caller used originally must not fail,
    # even though the task has already moved to version 3.
    replay = repo.transition("alice", task.task_id, 2, "awaiting_user_decision", key="state-1")

    assert replay.version == first.version
    with pytest.raises(ApplicationError, match="IDEMPOTENCY_CONFLICT"):
        repo.transition("alice", task.task_id, 2, "cancelled", key="state-1")


def test_illegal_state_transition_is_refused(tmp_path):
    repo = _repository(tmp_path / "plan.sqlite3")
    task = _task(repo)
    with pytest.raises(ApplicationError, match="STATE_TRANSITION"):
        repo.transition("alice", task.task_id, 1, "activated", key="skip")
    with pytest.raises(ValueError):
        repo.transition("alice", task.task_id, 1, "unknown_state", key="bad")


def test_expired_task_reads_as_expired_and_refuses_writes(tmp_path):
    path = tmp_path / "plan.sqlite3"
    repo = _repository(path)
    task = _task(repo)

    later = _repository(path, now=NOW + timedelta(days=31))
    expired = later.get("alice", task.task_id)
    assert expired.state == "expired"
    with pytest.raises(ApplicationError, match="TASK_EXPIRED"):
        later.transition("alice", task.task_id, task.version, "cancelled", key="late")


def test_candidate_expiry_is_shorter_than_the_task(tmp_path):
    repo = _repository(tmp_path / "plan.sqlite3")
    task = _task(repo)
    repo.grant("alice", task.task_id, 1, frozenset({"training"}), frozenset({"training"}), key="grant-1")
    submitted = repo.submit_bundle("alice", task.task_id, 2, "submit-1",
                                   CandidateBundle(patches=(_patch(),)), _verdict(passed=True))

    assert submitted.candidate_expires_at < submitted.expires_at


def test_delete_user_data_removes_every_row_for_that_owner_only(tmp_path):
    repo = _repository(tmp_path / "plan.sqlite3")
    mine = _task(repo, key="create-1", owner="alice")
    theirs = _task(repo, key="create-2", owner="bob")
    repo.grant("alice", mine.task_id, 1, frozenset({"training"}), frozenset({"training"}), key="grant-1")

    counts = repo.delete_user_data("alice")

    assert counts["plan_adjustment_sessions"] == 1
    assert counts["plan_task_permissions"] == 1
    assert counts["plan_task_receipts"] >= 2
    with pytest.raises(KeyError):
        repo.get("alice", mine.task_id)
    assert repo.get("bob", theirs.task_id).task_id == theirs.task_id


def test_snapshot_rejects_unbounded_values():
    with pytest.raises(ValueError):
        TaskSnapshot(task_id="", version=1, state="collecting", base_plan_id="p1",
                     base_head_revision=1, read_domains=frozenset({"training"}),
                     change_domains=frozenset({"training"}), constraint_digest="c" * 64,
                     candidate_id=None, candidate_digest=None, repair_rounds=0,
                     active_round_id=None, operation_id=None,
                     expires_at=NOW, candidate_expires_at=None)
    with pytest.raises(ValueError):
        TaskSnapshot(task_id="t1", version=1, state="made_up", base_plan_id="p1",
                     base_head_revision=1, read_domains=frozenset({"training"}),
                     change_domains=frozenset({"training"}), constraint_digest="c" * 64,
                     candidate_id=None, candidate_digest=None, repair_rounds=0,
                     active_round_id=None, operation_id=None,
                     expires_at=NOW, candidate_expires_at=None)
    with pytest.raises(ValueError):
        TaskSnapshot(task_id="t1", version=1, state="collecting", base_plan_id="p1",
                     base_head_revision=1, read_domains=frozenset({"training"}),
                     change_domains=frozenset({"training"}), constraint_digest="c" * 64,
                     candidate_id=None, candidate_digest=None, repair_rounds=0,
                     active_round_id=None, operation_id=None,
                     expires_at=NOW.replace(tzinfo=None), candidate_expires_at=None)


def test_every_state_is_known():
    assert {"collecting", "awaiting_scope_permission", "generating", "repairing",
            "awaiting_confirmation", "awaiting_user_decision", "activated",
            "cancelled", "expired"} == TASK_STATES


def _spawn_reserve(path, owner, task_id, version, operation_id, barrier, results):
    from backend.infrastructure.repositories.sqlite_plan_adjustment_repository import (
        SQLitePlanAdjustmentRepository,
    )
    from backend.infrastructure.sqlite.database import SQLiteDatabase

    repository = SQLitePlanAdjustmentRepository(SQLiteDatabase(path))
    barrier.wait(timeout=20)
    try:
        snapshot = repository.reserve_repair_round(owner, task_id, version, operation_id,
                                                   frozenset({"training"}))
        results.put(("won", snapshot.repair_rounds))
    except Exception as error:  # noqa: BLE001 - the child reports the failure verbatim
        results.put(("lost", type(error).__name__))
    finally:
        results.close()


def test_two_processes_cannot_both_take_the_last_round(tmp_path):
    path = tmp_path / "plan.sqlite3"
    repo = _repository(path)
    task = _task(repo)
    repo.grant("alice", task.task_id, 1, frozenset({"training"}), frozenset({"training"}), key="grant-1")
    first = repo.reserve_repair_round("alice", task.task_id, 2, "op-1", frozenset({"training"}))
    submitted = repo.submit_bundle("alice", task.task_id, first.version, "submit-1",
                                   CandidateBundle(patches=(_patch(),)), _verdict(passed=False))

    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = [context.Process(target=_spawn_reserve,
                                 args=(str(path), "alice", task.task_id, submitted.version,
                                       f"race-{index}", barrier, results))
                 for index in range(2)]
    outcomes = []
    try:
        for process in processes:
            process.start()
        for _ in processes:
            outcomes.append(results.get(timeout=30))
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

    assert sorted(outcome for outcome, _ in outcomes) == ["lost", "won"]
    assert repo.get("alice", task.task_id).repair_rounds == REPAIR_ROUND_LIMIT
