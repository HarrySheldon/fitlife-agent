"""Batch budget ledger: one allowance shared by every case in a run."""
from __future__ import annotations

import pytest

from backend.task_evaluation.budget import BatchBudget


def test_two_workers_compete_for_one_remaining_call():
    """With one call left, exactly one worker may reserve it."""
    budget = BatchBudget(limit=1)
    first = budget.reserve(1.0)
    assert first is not None
    assert budget.reserve(1.0) is None


def test_unknown_usage_retains_the_whole_reservation():
    """An unknown settlement keeps the reservation, so the batch cannot overspend."""
    budget = BatchBudget(limit=1)
    reservation = budget.reserve(1.0)
    budget.settle(reservation, None)
    assert budget.reserve(1.0) is None


def test_settled_usage_frees_the_unused_capacity():
    budget = BatchBudget(limit=2)
    reservation = budget.reserve(1.0)
    budget.settle(reservation, 1.0)
    assert budget.reserve(1.0) is not None


def test_settlement_above_the_reservation_is_rejected():
    budget = BatchBudget(limit=2)
    reservation = budget.reserve(1.0)
    with pytest.raises(ValueError):
        budget.settle(reservation, 5.0)


def test_negative_budget_is_rejected():
    with pytest.raises(ValueError):
        BatchBudget(limit=-1)


def test_token_rejection_does_not_leak_call_capacity():
    budget = BatchBudget(limit=2, token_limit=10)
    assert budget.reserve(1, 11) is None
    assert budget.reserve(2, 10) is not None


def test_concurrent_token_reservations_are_atomic():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    budget = BatchBudget(limit=2, token_limit=10)
    barrier = Barrier(2)
    def attempt():
        barrier.wait()
        return budget.reserve(1, 10)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: attempt(), range(2)))
    assert sum(result is not None for result in results) == 1
    assert budget.snapshot()["reserved_tokens"] == 10


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_nonfinite_budget_is_rejected(value):
    with pytest.raises(ValueError):
        BatchBudget(value)


def test_partial_unknown_settlement_cannot_replay_calls():
    budget = BatchBudget(2, 10)
    reservation = budget.reserve(1, 10)
    budget.settle(reservation, 1, None)
    with pytest.raises(ValueError):
        budget.settle(reservation, 1, 10)
    assert budget.snapshot()["spent_calls"] == 1


def test_failed_gateway_call_keeps_unknown_usage():
    from backend.task_evaluation.budget import MeteredMockGateway
    budget = BatchBudget(1, 10000)
    gateway = MeteredMockGateway(budget)
    def fail():
        raise RuntimeError("sensitive-text")
    with pytest.raises(RuntimeError):
        gateway._call(fail)
    assert gateway.failed_attempts == 1
    assert gateway.attempts == 1
    assert budget.snapshot()["reserved_calls"] == 1
    assert budget.snapshot()["reserved_tokens"] > 0


def test_oversized_output_retains_unknown_usage_and_prior_known_subtotal(tmp_path):
    from backend.task_evaluation.budget import MeteredMockGateway, BudgetExceeded
    from backend.task_evaluation.worker import collect_metrics
    budget = BatchBudget(2, 10000)
    gateway = MeteredMockGateway(budget)
    gateway._call(lambda: "safe")
    known = gateway.estimated_tokens
    assert known > 0
    with pytest.raises(BudgetExceeded):
        gateway._call(lambda: "x" * 10000)
    metrics = collect_metrics(tmp_path, None, gateway, {})
    assert metrics["estimated_tokens"] is None
    assert metrics["known_estimated_tokens"] == known
    assert gateway.attempts == 2
    assert gateway.failed_attempts == 1
    assert budget.snapshot()["spent_calls"] == 1
    assert budget.snapshot()["reserved_calls"] == 1
    assert budget.snapshot()["reserved_tokens"] > 0


def _spawn_reserve(channel, barrier):
    from backend.task_evaluation.budget import RemoteBudget, BudgetExceeded
    barrier.wait(timeout=10)
    try:
        RemoteBudget(channel).reserve(1, 10)
        channel.send({"winner": True})
    except BudgetExceeded:
        channel.send({"winner": False})
    finally:
        channel.close()


@pytest.mark.parametrize("calls,tokens", [(1, 20), (2, 10)])
def test_spawned_workers_share_atomic_call_and_token_budget(calls, tokens):
    import multiprocessing
    import time
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    budget = BatchBudget(calls, tokens)
    pipes = [context.Pipe() for _ in range(2)]
    processes = [context.Process(target=_spawn_reserve, args=(child, barrier)) for _, child in pipes]
    results = []
    try:
        for process in processes:
            process.start()
        deadline = time.monotonic() + 15
        while len(results) < 2 and time.monotonic() < deadline:
            for parent, _ in pipes:
                if parent.poll(0.01):
                    message = parent.recv()
                    if message.get("rpc") == "reserve":
                        reservation = budget.reserve(message["upper_bound"], message["token_upper_bound"])
                        parent.send({"ok": bool(reservation), "reservation": reservation})
                    elif "winner" in message:
                        results.append(message["winner"])
        assert sorted(results) == [False, True]
    finally:
        for process in processes:
            if process.pid and process.is_alive():
                process.terminate()
            if process.pid:
                process.join(timeout=5)
                process.close()
        for parent, child in pipes:
            parent.close()
            child.close()
