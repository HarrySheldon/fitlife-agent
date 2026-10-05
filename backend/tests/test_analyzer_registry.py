"""Adding a domain must mean registering an analysis, not editing the pipeline.

These tests are the falsifiable part of the extensibility claim: a brand new
analysis is registered, the planner activates it, and the workflow runs it without
any change to ``workflow.py``. If a future domain forces an edit to the pipeline
instead, these tests still pass but the design has regressed — so the assertion
that matters is that this file constructs the new domain entirely from the
registry.
"""
import asyncio

import pytest

from backend.agent.analyzers import ANALYZERS, Analyzer, AnalyzerRegistry
from backend.agent.contracts import AgentCommand
from backend.agent.route_contract import build_route_model
from backend.agent.runtime import AgentRuntime
from backend.agent.workflow import FitLifeWorkflow
from backend.infrastructure.agent_runtime.memory_run_repository import MemoryRunRepository
from backend.infrastructure.repositories.file_fitness_repository import FileFitnessRepository


EXECUTED: list[str] = []


def _sleep_analysis(context):
    EXECUTED.append(context.user_id or "")
    return {"summary": "avg 6.5 h", "nights_recorded": 7}


SLEEP_ANALYSIS = Analyzer(
    id="analyze_sleep",
    route_flag="needs_sleep_analysis",
    provides="sleep_analysis",
    requires=("profile",),
    run=_sleep_analysis,
    knowledge_scope=("sleep_rules.md",),
    title="sleep analysis",
)

EXTENDED_ANALYZERS = (*ANALYZERS, SLEEP_ANALYSIS)

# The planner contract is derived from the registry, so registering the analysis
# is what makes the planner able to ask for it.
SleepAwareRoute = build_route_model(EXTENDED_ANALYZERS, name="SleepAwareRoute")


class Gateway:
    model = "test-model"

    def plan_route(self, question):
        return SleepAwareRoute(
            intent="sleep_review",
            needs_meal_analysis=False,
            needs_sleep_analysis=True,
        )

    def write_answer(self, state):
        self.written = state
        return "## Sleep\nYou averaged 6.5 hours."


@pytest.fixture(autouse=True)
def _clear_executed():
    EXECUTED.clear()


def test_registry_order_and_activation_are_data_driven():
    registry = AnalyzerRegistry(EXTENDED_ANALYZERS)

    assert registry.ids() == ("analyze_meals", "analyze_workouts", "analyze_sleep")
    activated = registry.activated_by({"needs_sleep_analysis": True})
    assert [analyzer.id for analyzer in activated] == ["analyze_sleep"]
    assert registry.knowledge_scope({"needs_sleep_analysis": True}) == ("sleep_rules.md",)


def test_registered_analysis_runs_without_touching_the_workflow():
    """A domain added purely through the registry reaches tool_results."""
    repository = MemoryRunRepository()
    workflow = FitLifeWorkflow(
        FileFitnessRepository(),
        Gateway(),
        retriever=lambda *_: [],
        analyzers=AnalyzerRegistry(EXTENDED_ANALYZERS),
    )

    outcome = asyncio.run(
        AgentRuntime(repository=repository).execute(
            AgentCommand("chat", "how did I sleep this week?", "u1"), workflow
        )
    )

    assert outcome.status == "succeeded"
    assert EXECUTED == ["u1"]
    assert outcome.tool_results["sleep_analysis"] == {"summary": "avg 6.5 h", "nights_recorded": 7}
    assert "analyze_sleep" in outcome.trace["tool_calls"]
    # The existing analyses were not activated, so they must not have run.
    assert "meal_analysis" not in outcome.tool_results
    assert "workout_analysis" not in outcome.tool_results


def test_analysis_results_reach_the_writer_without_a_code_change():
    """tool_results is a generic mapping, so a new domain is visible to the model."""
    repository = MemoryRunRepository()
    gateway = Gateway()
    workflow = FitLifeWorkflow(
        FileFitnessRepository(),
        gateway,
        retriever=lambda *_: [],
        analyzers=AnalyzerRegistry(EXTENDED_ANALYZERS),
    )

    asyncio.run(
        AgentRuntime(repository=repository).execute(
            AgentCommand("chat", "how did I sleep?", "u1"), workflow
        )
    )

    assert gateway.written["tool_results"]["sleep_analysis"]["nights_recorded"] == 7


def test_registry_rejects_an_incomplete_analyzer():
    with pytest.raises(ValueError):
        Analyzer(id="", route_flag="needs_x", provides="x", run=_sleep_analysis)
    with pytest.raises(ValueError):
        Analyzer(id="x", route_flag="", provides="x", run=_sleep_analysis)
    with pytest.raises(ValueError):
        Analyzer(id="x", route_flag="needs_x", provides="", run=_sleep_analysis)


def test_analysis_context_cannot_write_or_reach_a_model():
    """An analysis is a read-only computation; that is what keeps numbers trustworthy."""
    from backend.agent.workflow import _AnalysisContext

    context = _AnalysisContext(repository=object(), user_id="u1", profile={"weight_kg": 70})

    assert context.user_id == "u1"
    assert context.profile == {"weight_kg": 70}
    for forbidden in ("gateway", "write_meals", "save", "model"):
        assert not hasattr(context, forbidden)
