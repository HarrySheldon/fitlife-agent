"""Entry-level evidence that the production path wires the review in.

The plan is explicit that creating a FitLifeWorkflow and injecting a fake reviewer is
not proof of integration: that tests the gate, which was already working, and says
nothing about whether the production entry point passes a mode and a gateway. These
tests drive the real entry object from graph.py with a fake provider and assert the
review request actually happened, by reading the events the run recorded.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.agent.contracts import AgentCommand
from backend.agent.runtime import AgentRuntime
from backend.application.ports.structured_model_gateway import StructuredModelResult
from backend.domain.user_preferences import UserPreferences
from backend.infrastructure.agent_runtime.memory_run_repository import MemoryRunRepository
from backend.safety.review import ReviewVerdict
from backend.tests.test_planner_boundary_tolerance import FileFitnessRepository
from backend.tools.data_access import DEFAULT_PROFILE


class _FreeFormGateway:
    """A ModelGateway that answers both writer and planner without a provider."""

    provider = "test"
    model = "test-model"

    def plan_route(self, question):
        from backend.agent.planner import PlannerRoute

        return PlannerRoute(
            intent="meal_analysis", needs_retrieval=False, needs_plan=False, needs_report=False
        )

    def write_answer(self, state):
        return "你日均蛋白 98 克，目标 126 克。"


class _FakeStructuredGateway:
    model = "test-model"

    def __init__(self, verdict=None, error=None):
        self.verdict = verdict or ReviewVerdict(outcome="allow", risk_category="low")
        self.error = error
        self.calls = 0

    def parse_structured(self, *, instructions, input_text, response_model):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return StructuredModelResult(output=self.verdict, model="test-model", usage={})


def _run(mode: str, structured_gateway, monkeypatch):
    """Drive the real entry object, not a hand-built workflow."""
    from backend.agent import graph

    monkeypatch.setattr(graph, "_review_mode", lambda: mode)
    repository = FileFitnessRepository()
    repository.read_profile = lambda user_id=None: DEFAULT_PROFILE
    run_repository = MemoryRunRepository()
    workflow = graph._LazyFitLifeWorkflow(
        repository=repository,
        gateway=_FreeFormGateway(),
        user_id="u1",
        preferences=UserPreferences(),
        structured_gateway=structured_gateway,
    )
    runtime = AgentRuntime(repository=run_repository)
    outcome = asyncio.run(
        runtime.execute(AgentCommand("chat", "这周蛋白吃够了吗", "u1"), workflow)
    )
    # events() is scoped by user, so the same identity the command carried.
    events = [event for event in run_repository.events(outcome.run_id, "u1")]
    return outcome, events, structured_gateway


def _review_events(events):
    return [e.payload for e in events if e.event_type == "SAFETY_REVIEWED"]


def test_the_entry_point_runs_no_review_when_the_mode_is_off(monkeypatch):
    outcome, events, gateway = _run("off", _FakeStructuredGateway(), monkeypatch)

    assert outcome.status == "succeeded"
    assert gateway.calls == 0
    assert _review_events(events) == [{"review_mode": "off", "review_status": "disabled"}]


def test_the_entry_point_actually_calls_the_gateway_in_shadow(monkeypatch):
    """The assertion that matters: the production path made the request."""
    outcome, events, gateway = _run("shadow", _FakeStructuredGateway(), monkeypatch)

    assert outcome.status == "succeeded"
    assert gateway.calls == 1
    assert _review_events(events) == [{"review_mode": "shadow", "review_status": "allow"}]


def test_shadow_records_a_refusal_without_changing_the_answer(monkeypatch):
    gateway = _FakeStructuredGateway(ReviewVerdict(outcome="refuse", risk_category="harassment"))

    outcome, events, fake = _run("shadow", gateway, monkeypatch)

    assert outcome.status == "succeeded"
    assert fake.calls == 1
    assert _review_events(events) == [{"review_mode": "shadow", "review_status": "refuse"}]
    assert outcome.result.answer_markdown.strip()


def test_a_provider_failure_in_shadow_is_recorded_and_the_answer_survives(monkeypatch):
    gateway = _FakeStructuredGateway(error=RuntimeError("provider down"))

    outcome, events, fake = _run("shadow", gateway, monkeypatch)

    assert fake.calls == 1
    assert outcome.status == "succeeded"
    assert _review_events(events) == [{"review_mode": "shadow", "review_status": "unavailable"}]


def test_enforce_turns_a_review_refusal_into_a_withheld_answer(monkeypatch):
    """The refusal propagates out of the run, and the reason is recorded."""
    from backend.agent import graph
    from backend.safety.gate import SafetyRefusal

    monkeypatch.setattr(graph, "_review_mode", lambda: "enforce")
    repository = FileFitnessRepository()
    repository.read_profile = lambda user_id=None: DEFAULT_PROFILE
    run_repository = MemoryRunRepository()
    gateway = _FakeStructuredGateway(
        ReviewVerdict(outcome="refuse", risk_category="harassment")
    )
    workflow = graph._LazyFitLifeWorkflow(
        repository=repository,
        gateway=_FreeFormGateway(),
        user_id="u1",
        preferences=UserPreferences(),
        structured_gateway=gateway,
    )

    with pytest.raises(SafetyRefusal):
        asyncio.run(
            AgentRuntime(repository=run_repository).execute(
                AgentCommand("chat", "这周蛋白吃够了吗", "u1"), workflow
            )
        )

    assert gateway.calls == 1


def test_enforce_without_a_structured_gateway_is_a_configuration_error(monkeypatch):
    """Asked for enforcement, a deployment must not silently receive none."""
    from backend.agent import graph
    from backend.domain.errors import ApplicationError

    monkeypatch.setattr(graph, "_review_mode", lambda: "enforce")
    repository = FileFitnessRepository()
    repository.read_profile = lambda user_id=None: DEFAULT_PROFILE
    run_repository = MemoryRunRepository()
    workflow = graph._LazyFitLifeWorkflow(
        repository=repository,
        gateway=_FreeFormGateway(),
        user_id="u1",
        preferences=UserPreferences(),
        structured_gateway=None,
    )

    with pytest.raises(ApplicationError) as raised:
        asyncio.run(
            AgentRuntime(repository=run_repository).execute(
                AgentCommand("chat", "这周蛋白吃够了吗", "u1"), workflow
            )
        )

    assert raised.value.code == "CONFIGURATION_INVALID"


@pytest.mark.parametrize("bad", ["always", "ON", "true"])
def test_an_invalid_mode_is_rejected_by_configuration(bad):
    from pydantic import ValidationError

    from backend.config import Settings

    with pytest.raises(ValidationError):
        Settings(safety_review_mode=bad)
