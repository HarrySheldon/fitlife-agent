from __future__ import annotations

import pytest

from backend.agent import graph as agent_graph
from backend.agent.planner import PlannerRoute


def test_build_graph_exposes_fitlife_workflow_nodes():
    graph = agent_graph.build_graph()

    assert graph is not None
    node_names = set(graph.get_graph().nodes)
    assert {
        "planner",
        "profile_loader",
        "data_analyzer",
        "retriever",
        "generator",
        "validator",
        "writer",
        "trace_builder",
    }.issubset(node_names)


def test_run_fitlife_agent_invokes_compiled_graph(monkeypatch):
    invoked_states: list[dict] = []

    class FakeCompiledGraph:
        def invoke(self, state: dict) -> dict:
            invoked_states.append(state)
            return {
                "final_answer": "fake graph answer",
                "intent": "knowledge_qa",
                "trace": {
                    "intent": "knowledge_qa",
                    "tool_calls": ["retrieve_knowledge"],
                    "retrieved_sources": ["fitness_rules.md"],
                    "validation_passed": True,
                    "warnings": [],
                },
                "tool_results": {},
                "retrieved_docs": [{"source": "fitness_rules.md", "text": "demo"}],
            }

    monkeypatch.setattr(agent_graph, "build_graph", lambda: FakeCompiledGraph())

    result = agent_graph.run_fitlife_agent("How should I train this week?")

    assert invoked_states
    assert invoked_states[0]["user_query"] == "How should I train this week?"
    assert result == {
        "answer_markdown": "fake graph answer",
        "intent": "knowledge_qa",
        "trace": {
            "intent": "knowledge_qa",
            "tool_calls": ["retrieve_knowledge"],
            "retrieved_sources": ["fitness_rules.md"],
            "validation_passed": True,
            "warnings": [],
        },
        "tool_results": {},
        "sources": [{"source": "fitness_rules.md", "text": "demo"}],
    }


def test_planner_node_uses_llm_route_when_available(monkeypatch):
    monkeypatch.setattr(
        agent_graph,
        "try_plan_route_with_llm",
        lambda question: PlannerRoute(intent="knowledge_qa", needs_retrieval=True),
    )

    update = agent_graph.planner_node({"user_query": "Give me general fitness advice."})

    assert update["intent"] == "knowledge_qa"
    assert update["tool_requests"]["needs_retrieval"] is True
    assert update["llm_used"] is True


def test_writer_node_uses_llm_answer_when_available(monkeypatch):
    monkeypatch.setattr(agent_graph, "try_write_answer_with_llm", lambda state: "## LLM Answer")

    update = agent_graph.writer_node({"intent": "knowledge_qa", "tool_results": {}, "retrieved_docs": []})

    assert update == {"final_answer": "## LLM Answer", "llm_used": True}


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
    result = agent_graph.run_fitlife_agent(question)

    assert result["answer_markdown"]
    assert result["intent"] == expected_intent
    trace = result["trace"]
    assert trace["intent"] == expected_intent
    assert expected_tools.issubset(set(trace["tool_calls"]))
    assert isinstance(trace["retrieved_sources"], list)
    assert isinstance(trace["validation_passed"], bool)
    assert isinstance(trace["warnings"], list)
    assert trace["retrieved_sources"] == sorted({doc["source"] for doc in result["sources"]})
    assert expected_sources.issubset(set(trace["retrieved_sources"]))
