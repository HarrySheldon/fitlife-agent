"""Live execution boundary: admission first, then a gateway, then accounted attempts.

There is exactly one allowed order:

    admission() -> factory() -> attempt inside a reservation

Nothing in this module opens a socket, reads a credential or builds an HTTP client. It
defines the *boundary*; the actual adapter is supplied by the caller only after
admission has passed.

Two further properties matter as much as the order:

* A refused reservation must stop the attempt *before* it starts. Reserving after the
  call would mean the call was already paid for.
* An attempt that raised, or whose usage is unknown, still settles. Leaving a
  reservation open would silently free budget that was in fact spent.
"""
from __future__ import annotations

from typing import Any, Callable


class BrokerRejected(RuntimeError):
    """The parent broker refused a reservation, so no attempt may start."""


class LiveGatewayDenied(RuntimeError):
    """A gateway that was never admitted; every call raises instead of silently no-oping."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code

    def generate(self, **_: Any) -> None:
        raise ValueError(self.code) from None

    def analyze(self, **_: Any) -> None:
        raise ValueError(self.code) from None

    def decide(self, **_: Any) -> None:
        raise ValueError(self.code) from None

    def review(self, **_: Any) -> None:
        raise ValueError(self.code) from None


# The only message shapes the worker/parent boundary carries. A file path, a URL or
# arbitrary Python would widen the boundary into "the child can ask the parent to do
# anything", which is precisely what the isolation is meant to prevent.
_ALLOWED_MESSAGE_KINDS = frozenset({"generation", "structured", "decision", "review"})


def allowed_message_kinds() -> frozenset[str]:
    return _ALLOWED_MESSAGE_KINDS


def build_admitted_gateway(*, admission: Callable[[], None],
                           factory: Callable[[], Any]) -> Any:
    """Run admission, and only then construct a gateway.

    A factory failure is deliberately *not* converted into an admission failure: the
    two mean different things to an operator, and conflating them would hide a
    provider problem behind a policy error.
    """
    admission()
    return factory()


def run_admitted_attempt(*, broker, kind: str, upper_bound: float,
                         token_upper_bound: int, attempt: Callable[[], Any],
                         usage: float | None = None,
                         token_usage: int | None = None) -> Any:
    """Reserve, run one attempt, then always settle.

    ``usage=None`` keeps the whole reservation: an unknown usage is not a zero usage.
    """
    if kind not in _ALLOWED_MESSAGE_KINDS:
        raise ValueError(f"Unsupported message kind: {kind}")
    reservation = broker.reserve(kind=kind, upper_bound=upper_bound,
                                token_upper_bound=token_upper_bound)
    try:
        return attempt()
    finally:
        broker.settle(reservation=reservation, usage=usage, token_usage=token_usage)


class FakeGateway:
    """An offline provider used to exercise the whole path without a network.

    It exists so a live-shaped run can be tested end to end. It records every attempt
    in the ledger, so a test can prove "the provider was never reached" by observing
    that no attempt was opened, rather than by trusting a counter it maintains.

    Failure modes are explicit: ``outcome`` selects what every boundary does, so the
    timeout and cancellation drills exercise the same code path the adapter will.
    """

    provider = "fake"
    model = "fake-admitted-v1"

    def __init__(self, *, ledger=None, outcome: str = "ok", payload: Any = None) -> None:
        self._ledger = ledger
        self._outcome = outcome
        self._payload = payload if payload is not None else {}
        self.calls: list[str] = []

    def _run(self, boundary: str) -> Any:
        self.calls.append(boundary)
        attempt_id = self._ledger.open("physical_model") if self._ledger is not None else None
        closed = False
        try:
            if self._outcome == "timeout":
                raise TimeoutError(f"{boundary} timed out")
            if self._outcome == "cancel":
                if attempt_id is not None:
                    self._ledger.cancel(attempt_id)
                    closed = True
                raise KeyboardInterrupt(f"{boundary} cancelled")
            result = self._payload
            if attempt_id is not None:
                self._ledger.complete(attempt_id)
                closed = True
            return result
        finally:
            # Any exception path that has not closed its own attempt is labelled a
            # failure here, so an open attempt can never be read as a success.
            if attempt_id is not None and not closed:
                try:
                    self._ledger.fail(attempt_id)
                except ValueError:
                    pass

    def generate(self, **_: Any) -> Any:
        return self._run("generation")

    def analyze(self, **_: Any) -> Any:
        return self._run("structured")

    def decide(self, **_: Any) -> Any:
        return self._run("decision")

    def review(self, **_: Any) -> Any:
        return self._run("review")
