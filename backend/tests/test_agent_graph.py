from __future__ import annotations

import pytest
from types import SimpleNamespace

from backend.agent import graph as agent_graph
from backend.agent.planner import PlannerRoute, plan_route
from backend.infrastructure.repositories.file_fitness_repository import FileFitnessRepository


class RoutingGateway:
    model = "test-model"

    def plan_route(self, question: str) -> PlannerRoute:
        return plan_route(question)

    def write_answer(self, state: dict) -> str:
        return "## Model answer\nGenerated from validated tool results."


def test_run_contextual_coach_action_adds_context_to_prompt_and_trace(monkeypatch):
    captured: dict[str, str | None] = {}

    def fake_run(question: str, user_id: str | None = None, **kwargs) -> dict:
        captured["question"] = question
        captured["user_id"] = user_id
        return {
            "answer_markdown": "Contextual model answer",
            "intent": "meal_analysis",
            "trace": {"tool_calls": ["analyze_meals"], "llm_used": True, "llm_answer_used": True},
            "sources": [],
            "model": "test-model",
            "request_id": "request-1",
        }

    class CapturingRuntime:
        def execute_sync(self, command, workflow):
            return SimpleNamespace(to_dict=lambda: fake_run(command.question, command.user_id))

    monkeypatch.setattr(agent_graph, "DEFAULT_AGENT_RUNTIME", CapturingRuntime())

    result = agent_graph.run_contextual_coach_action(
        surface="plan",
        action="adjust_next_plan",
        date="2026-07-09",
        question="Keep it simple.",
        user_id="user-1",
    )

    assert "Create a plan for next week" in str(captured["question"])
    assert "2026-07-09" in str(captured["question"])
    assert "Keep it simple." in str(captured["question"])
    assert captured["user_id"] == "user-1"
    assert result["answer_markdown"] == "Contextual model answer"
    assert result["trace"]["surface"] == "plan"
    assert result["trace"]["coach_action"] == "adjust_next_plan"


def test_context_loader_failure_has_persisted_run_identity(monkeypatch):
    from backend.agent.runtime import AgentRuntime
    runtime = AgentRuntime()
    monkeypatch.setattr(agent_graph, "DEFAULT_AGENT_RUNTIME", runtime)
    def broken_context(*args):
        raise ValueError("private context failure")
    monkeypatch.setattr(agent_graph, "_build_contextual_tool_context", broken_context)
    with pytest.raises(ValueError) as caught:
        agent_graph.run_contextual_coach_action(
            surface="today", action="explain_today", date=None,
            repository=object(), gateway=RoutingGateway(), user_id="owner",
        )
    run = runtime.repository.get(caught.value.run_id, "owner")
    assert run.status == "failed"
    assert run.failure_stage == "context_loader"
    assert run.request_id == caught.value.request_id


@pytest.mark.parametrize(
    ("question", "expected_intent", "expected_tools", "expected_sources"),
    [
        (
            "Did I hit my protein target this week?",
            "meal_analysis",
            {"load_profile", "analyze_meals"},
            set(),
        ),
        (
            "What can replace chicken breast for protein?",
            "knowledge_qa",
            {"retrieve_knowledge"},
            {"meal_templates.md"},
        ),
        (
            "Create a workout plan for next week.",
            "plan_generation",
            {"load_profile", "analyze_workouts", "retrieve_knowledge", "generate_next_week_plan", "validate_plan"},
            {"fitness_rules.md"},
        ),
        (
            "Create a weekly summary report.",
            "weekly_report",
            {"load_profile", "analyze_meals", "analyze_workouts", "retrieve_knowledge", "generate_weekly_report"},
            {"nutrition_guidelines.md"},
        ),
    ],
)
def test_run_fitlife_agent_preserves_trace_contract(
    question: str,
    expected_intent: str,
    expected_tools: set[str],
    expected_sources: set[str],
):
    result = agent_graph.run_fitlife_agent(
        question,
        repository=FileFitnessRepository(),
        gateway=RoutingGateway(),
    )

    assert result["answer_markdown"].startswith("## Model answer")
    assert result["intent"] == expected_intent
    trace = result["trace"]
    assert trace["intent"] == expected_intent
    assert expected_tools.issubset(set(trace["tool_calls"]))
    assert isinstance(trace["retrieved_sources"], list)
    assert isinstance(trace["validation_passed"], bool)
    assert isinstance(trace["warnings"], list)
    assert trace["llm_used"] is True
    assert trace["llm_answer_used"] is True
    assert trace["retrieved_sources"] == sorted({doc["source"] for doc in result["sources"]})
    assert expected_sources.issubset(set(trace["retrieved_sources"]))
