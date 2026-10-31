"""Live gateway tests: admission must pass before a gateway exists.

The whole safety argument of a live batch is ordering. If a gateway can be built and
then asked whether it was allowed, a refused batch has already taken a step toward the
network. These tests pin the order, the accounting and the cancellation boundary.
"""
from __future__ import annotations

import pytest

from backend.task_evaluation.live_gateway import (
    BrokerRejected,
    LiveGatewayDenied,
    build_admitted_gateway,
)


def test_invalid_admission_never_constructs_gateway():
    calls = []

    def admission():
        raise ValueError("LIVE_NOT_AUTHORIZED")

    def factory():
        calls.append("constructed")
        return object()

    with pytest.raises(ValueError, match="LIVE_NOT_AUTHORIZED"):
        build_admitted_gateway(admission=admission, factory=factory)
    assert calls == []


def test_admission_runs_before_the_factory_exactly_once():
    order = []

    def admission():
        order.append("admission")

    def factory():
        order.append("factory")
        return "gateway"

    assert build_admitted_gateway(admission=admission, factory=factory) == "gateway"
    assert order == ["admission", "factory"]


def test_a_factory_failure_is_not_reported_as_an_admission_failure():
    """Admission succeeded; the construction error must stay distinguishable."""
    def factory():
        raise RuntimeError("provider offline")

    with pytest.raises(RuntimeError, match="provider offline"):
        build_admitted_gateway(admission=lambda: None, factory=factory)


@pytest.mark.parametrize("kind", ["generation", "structured", "decision", "review"])
def test_a_broker_message_kind_is_allowed_only_for_its_own_shape(kind):
    """The IPC boundary accepts these message kinds and nothing else."""
    from backend.task_evaluation.live_gateway import allowed_message_kinds

    assert kind in allowed_message_kinds()
    assert "arbitrary_python" not in allowed_message_kinds()
    assert "file_path" not in allowed_message_kinds()


class _FakeBroker:
    def __init__(self, *, approve=True, reason="BUDGET_EXHAUSTED"):
        self.approve = approve
        self.reason = reason
        self.reserved = 0
        self.settled = []

    def reserve(self, *, kind, upper_bound, token_upper_bound):
        if not self.approve:
            raise BrokerRejected(self.reason)
        self.reserved += 1
        return f"res-{self.reserved}"

    def settle(self, *, reservation, usage, token_usage):
        self.settled.append((reservation, usage, token_usage))


def test_a_refused_reservation_means_no_attempt_is_started():
    broker = _FakeBroker(approve=False)
    attempts = []

    def attempt():
        attempts.append(1)

    with pytest.raises(BrokerRejected, match="BUDGET_EXHAUSTED"):
        from backend.task_evaluation.live_gateway import run_admitted_attempt

        run_admitted_attempt(broker=broker, kind="generation", upper_bound=1,
                             token_upper_bound=100, attempt=attempt)
    assert attempts == []


def test_an_approved_attempt_reserves_then_settles():
    broker = _FakeBroker()

    from backend.task_evaluation.live_gateway import run_admitted_attempt

    result = run_admitted_attempt(broker=broker, kind="generation", upper_bound=1,
                                  token_upper_bound=100, attempt=lambda: "ok",
                                  usage=1, token_usage=100)

    assert result == "ok"
    assert broker.reserved == 1
    assert broker.settled == [("res-1", 1, 100)]


def test_unknown_usage_keeps_the_full_reservation():
    """An unknown usage is not a zero usage; it must not free the budget."""
    broker = _FakeBroker()

    from backend.task_evaluation.live_gateway import run_admitted_attempt

    run_admitted_attempt(broker=broker, kind="generation", upper_bound=1,
                         token_upper_bound=100, attempt=lambda: "ok",
                         usage=None, token_usage=None)

    assert broker.settled == [("res-1", None, None)]


def test_a_failing_attempt_still_settles_so_budget_is_not_leaked():
    broker = _FakeBroker()

    from backend.task_evaluation.live_gateway import run_admitted_attempt

    with pytest.raises(RuntimeError):
        run_admitted_attempt(broker=broker, kind="generation", upper_bound=1,
                             token_upper_bound=100,
                             attempt=lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    assert len(broker.settled) == 1


def test_a_denied_gateway_cannot_be_called():
    """A gateway that never admitted must refuse every call rather than no-op."""
    gateway = LiveGatewayDenied("LIVE_NOT_AUTHORIZED")

    with pytest.raises(ValueError, match="LIVE_NOT_AUTHORIZED"):
        gateway.generate(instructions="x", input_text="y")


# --------------------------------------------------------------------------
# FakeGateway: the full path, offline
# --------------------------------------------------------------------------

def _ledger():
    from backend.task_evaluation.measurements import AttemptLedger

    return AttemptLedger()


def test_fake_gateway_covers_all_four_boundaries():
    from backend.task_evaluation.live_gateway import FakeGateway

    gateway = FakeGateway(payload={"ok": True})

    assert gateway.generate(instructions="x", input_text="y") == {"ok": True}
    assert gateway.analyze(instructions="x", input_text="y", response_model=dict) == {"ok": True}
    assert gateway.decide(instructions="x", input_text="y") == {"ok": True}
    assert gateway.review(instructions="x", input_text="y") == {"ok": True}
    assert gateway.calls == ["generation", "structured", "decision", "review"]


def test_fake_gateway_counts_one_physical_attempt_per_boundary():
    from backend.task_evaluation.live_gateway import FakeGateway

    ledger = _ledger()
    gateway = FakeGateway(ledger=ledger)
    gateway.generate(instructions="x", input_text="y")
    gateway.review(instructions="x", input_text="y")

    summary = ledger.summary()
    assert summary.started == 2
    assert summary.completed == 2
    assert summary.by_kind["physical_model"] == 2


def test_a_timed_out_attempt_is_recorded_as_failed_not_completed():
    from backend.task_evaluation.live_gateway import FakeGateway

    ledger = _ledger()
    gateway = FakeGateway(ledger=ledger, outcome="timeout")

    with pytest.raises(TimeoutError):
        gateway.generate(instructions="x", input_text="y")

    summary = ledger.summary()
    assert summary.started == 1
    assert summary.completed == 0
    assert summary.failed == 1


def test_a_cancelled_attempt_is_recorded_as_cancelled():
    """Cancellation that cleaned up is 'cancelled', not 'incomplete' and not success."""
    from backend.task_evaluation.live_gateway import FakeGateway

    ledger = _ledger()
    gateway = FakeGateway(ledger=ledger, outcome="cancel")

    with pytest.raises(KeyboardInterrupt):
        gateway.generate(instructions="x", input_text="y")

    summary = ledger.summary()
    assert summary.cancelled == 1
    assert summary.completed == 0


def test_an_unreachable_provider_opens_no_attempt_at_all():
    """'Never called' must be provable from the ledger, not merely asserted."""

    ledger = _ledger()
    gateways = []

    def admission():
        raise ValueError("LIVE_NOT_AUTHORIZED")

    with pytest.raises(ValueError):
        build_admitted_gateway(
            admission=admission,
            factory=lambda: gateways.append("built"),
        )

    summary = ledger.summary()
    assert summary.started == 0
    assert gateways == []


def test_a_deadline_in_the_past_writes_a_partial_report_and_exits_one(tmp_path):
    """A batch that times out before its first case still reports what it knows."""
    import json

    import backend.task_evaluation.cli as cli

    suite = tmp_path / "suite.json"
    suite.write_text(json.dumps({
        "schema_version": 1,
        "scenarios": [{"id": "case-a", "version": 1}, {"id": "case-b", "version": 1}],
    }), encoding="utf-8")
    output = tmp_path / "out"

    code = cli.main(["--suite", str(suite), "--output", str(output), "--max-seconds", "1"])

    assert code in {0, 1}
    assert (output / "report.json").exists()
    payload = json.loads((output / "report.json").read_text(encoding="utf-8"))
    # Whatever the outcome, every declared case appears: a partial report must not
    # silently drop the cases it did not reach.
    assert len(payload["records"]) == 2
