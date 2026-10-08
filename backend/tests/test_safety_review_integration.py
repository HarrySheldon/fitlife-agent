"""The review runs inside the Runtime, and its failures stay distinguishable.

Two things are being pinned here. First, that the review is one budgeted, cancellable
model call rather than a request made from inside the gate. Second, that a provider
failure and an ended run are not the same event: the first means the review did not
happen, the second means there is no run left to answer, and reporting the second as
the first would turn a cancelled run into a successful one with a weaker check.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.agent.runtime import BudgetExceeded, RunCancelled, RunTimedOut
from backend.agent.semantic_review import (
    ObservationReviewer,
    ReviewUnavailable,
    collect_review,
)
from backend.application.ports.structured_model_gateway import StructuredModelResult
from backend.safety.review import ReviewVerdict


class _Gateway:
    model = "test-model"

    def __init__(self, verdict=None, error=None):
        self.verdict = verdict
        self.error = error
        self.calls = 0

    def parse_structured(self, *, instructions, input_text, response_model):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return StructuredModelResult(output=self.verdict, model="test-model", usage={})


class _Context:
    """The parts of RuntimeContext this orchestration touches."""

    def __init__(self, error=None):
        self.context_chars = 0
        self.output_chars = 0
        self.tools: list[str] = []
        self.error = error

    def consume_context(self, text):
        self.context_chars += len(text)

    def consume_output(self, text):
        self.output_chars += len(text)

    async def tool(self, name, replay, operation):
        self.tools.append(name)
        if self.error is not None:
            raise self.error
        return operation()


def _allow():
    return ReviewVerdict(outcome="allow", risk_category="low")


def _refuse():
    return ReviewVerdict(outcome="refuse", risk_category="harassment")


def _collect(mode, gateway, context=None):
    return asyncio.run(
        collect_review(context or _Context(), gateway, mode, "这周蛋白吃够了吗", "你日均蛋白 98 克。")
    )


# --------------------------------------------------------------------------
# off
# --------------------------------------------------------------------------

def test_off_makes_no_call_and_says_so():
    gateway = _Gateway(_allow())

    observation = _collect("off", gateway)

    assert observation.status == "disabled"
    assert gateway.calls == 0


# --------------------------------------------------------------------------
# the call is a Runtime tool
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["shadow", "enforce"])
def test_the_review_is_one_runtime_tool_call(mode):
    context = _Context()

    observation = _collect(mode, _Gateway(_allow()), context)

    assert context.tools == ["safety_review_model"]
    assert observation.status == "allow"


def test_the_input_is_charged_before_the_request_is_made():
    """A run that cannot afford the review must not make it."""
    context = _Context()

    _collect("shadow", _Gateway(_allow()), context)

    assert context.context_chars > 0


def test_the_output_is_charged_too():
    context = _Context()

    _collect("shadow", _Gateway(_allow()), context)

    assert context.output_chars > 0


# --------------------------------------------------------------------------
# the distinction that matters
# --------------------------------------------------------------------------

@pytest.mark.parametrize("error", [RunCancelled("cancelled"), RunTimedOut("timed out"),
                                   BudgetExceeded("budget")])
def test_an_ended_run_is_propagated_not_downgraded(error):
    """These are terminal states; calling them 'review unavailable' would hide them."""
    gateway = _Gateway(_allow())

    with pytest.raises(type(error)):
        _collect("enforce", gateway, _Context(error=error))


def test_a_provider_failure_is_an_unavailable_review():
    observation = _collect("enforce", _Gateway(_allow(), error=RuntimeError("provider down")))

    assert observation.status == "unavailable"
    assert observation.decision is None


def test_a_provider_failure_does_not_carry_the_exception_text():
    observation = _collect(
        "enforce", _Gateway(_allow(), error=RuntimeError("key sk-secret at 10.0.0.1"))
    )

    assert "sk-secret" not in repr(observation)
    assert "10.0.0.1" not in repr(observation)


# --------------------------------------------------------------------------
# what the gate is handed
# --------------------------------------------------------------------------

def test_shadow_never_changes_the_disposition():
    """Shadow observes; the answer is untouched by construction."""
    observation = _collect("shadow", _Gateway(_refuse()))

    assert observation.status == "refuse"
    reviewer = ObservationReviewer(observation, "shadow")
    assert reviewer.review("问题", "草稿").outcome == "allow"


def test_enforce_carries_the_refusal_to_the_gate():
    observation = _collect("enforce", _Gateway(_refuse()))

    reviewer = ObservationReviewer(observation, "enforce")
    decision = reviewer.review("问题", "草稿")

    assert decision.outcome == "refuse"
    assert decision.risk_category == "harassment"


def test_enforce_allows_when_the_review_allows():
    observation = _collect("enforce", _Gateway(_allow()))

    assert ObservationReviewer(observation, "enforce").review("问题", "草稿").outcome == "allow"


def test_an_unavailable_review_raises_so_the_gate_keeps_its_own_answer():
    """Returning allow here would claim a review happened and approved."""
    observation = _collect("enforce", _Gateway(_allow(), error=RuntimeError("down")))

    with pytest.raises(ReviewUnavailable):
        ObservationReviewer(observation, "enforce").review("问题", "草稿")


# --------------------------------------------------------------------------
# observability vocabulary
# --------------------------------------------------------------------------

def test_the_event_payload_accepts_the_controlled_review_fields():
    from backend.agent.persistence import safe_payload

    payload = safe_payload({"review_mode": "shadow", "review_status": "refuse"})

    assert payload == {"review_mode": "shadow", "review_status": "refuse"}


@pytest.mark.parametrize("payload", [
    {"review_mode": "always"},
    {"review_status": "maybe"},
])
def test_the_event_payload_rejects_values_outside_the_vocabulary(payload):
    from backend.agent.persistence import safe_payload

    with pytest.raises(ValueError):
        safe_payload(payload)
