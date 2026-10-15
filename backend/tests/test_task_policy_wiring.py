"""Production entry/runtime/adapters exercise the independent policy seams."""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from backend.agent import graph
from backend.agent.planner import PlannerRoute
from backend.agent.runtime import AgentRuntime
from backend.agent.tasks.capabilities import AuthorizedTaskReads
from backend.agent.tasks.input_contracts import ChatInput, FieldPatch


class SpyRepository:
    def __init__(self):
        self.reads = []

    def read_profile(self, owner):
        self.reads.append(("profile", owner))
        return SimpleNamespace(model_dump=lambda: {
            "daily_protein_target": 120, "daily_calorie_target": 2200,
            "allergies_or_restrictions": ["peanuts"], "diet_preferences": ["vegetarian"],
            "age": 42, "weight_kg": 78, "private_note": "secret personal text",
        })

    def read_meals(self, owner):
        self.reads.append(("meals", owner))
        return []

    def read_workouts(self, owner):
        self.reads.append(("workouts", owner))
        return []


def runtime_at_public_entry(monkeypatch):
    runtime = AgentRuntime()
    monkeypatch.setattr(graph, "DEFAULT_AGENT_RUNTIME", runtime)
    monkeypatch.setattr(graph, "_review_mode", lambda: "off")
    monkeypatch.setattr(graph, "_grounding_mode", lambda: "legacy")
    return runtime


@pytest.mark.parametrize("entry", ["chat", "coach"])
@pytest.mark.parametrize("question", ["帮我选股票", "Which stocks should I buy?"])
def test_public_out_of_scope_has_zero_private_or_provider_access(monkeypatch, entry, question):
    runtime_at_public_entry(monkeypatch)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("forbidden")
        raise AssertionError("Boundary crossed")

    monkeypatch.setattr(graph, "get_fitness_repository", forbidden)
    monkeypatch.setattr(graph, "_resolve_gateway", forbidden)
    monkeypatch.setattr(graph, "_build_contextual_tool_context", forbidden)
    monkeypatch.setattr("backend.agent.workflow.retrieve_knowledge", forbidden)
    repository = SpyRepository()
    if entry == "chat":
        result = graph.run_fitlife_agent(question, "owner", repository=repository)
    else:
        result = graph.run_contextual_coach_action("today", "explain_today", None, question,
                                                   "owner", repository=repository)
    assert result["trace"]["scope"] == "out_of_scope"
    assert result["trace"]["tool_calls"] == []
    assert repository.reads == calls == []


def test_coach_raw_unknown_question_cannot_borrow_template_permission(monkeypatch):
    runtime_at_public_entry(monkeypatch)
    planned = []
    repository = SpyRepository()

    class Gateway:
        model = "test-model"

        def plan_route(self, text):
            planned.append(text)
            return PlannerRoute(intent="meal_analysis", needs_meal_analysis=True, needs_retrieval=True)

        def write_answer(self, state):
            raise AssertionError("Writer must not run")

    def forbidden(*args):
        raise AssertionError("Page context must not load")

    monkeypatch.setattr(graph, "_build_contextual_tool_context", forbidden)
    result = graph.run_contextual_coach_action("today", "explain_today", None,
        "Write a political essay", "owner", repository=repository, gateway=Gateway())
    assert planned == ["Write a political essay"]
    assert result["trace"]["needs_clarification"]
    assert repository.reads == []


def test_empty_coach_question_uses_code_owned_page_intent(monkeypatch):
    runtime_at_public_entry(monkeypatch)
    seen = []
    repository = SpyRepository()

    class Gateway:
        model = "test-model"

        def plan_route(self, question):
            seen.append(question)
            return PlannerRoute(intent="knowledge_qa")

        def write_answer(self, state):
            return "建议保持规律训练。"

    monkeypatch.setattr(graph, "_build_contextual_tool_context", lambda *args: ({}, []))
    result = graph.run_contextual_coach_action("today", "explain_today", None, None,
        "owner", repository=repository, gateway=Gateway())
    assert len(seen) == 1 and "today" in seen[0].lower()
    assert result["trace"]["llm_answer_used"]
    assert repository.reads == [("profile", "owner")]


@pytest.mark.parametrize("protocol", ["chat", "responses"])
def test_actual_provider_writer_receives_chat_contract_and_all_necessary_facts(monkeypatch, protocol):
    from backend.infrastructure.model_gateway.openai_chat_completions import OpenAIChatCompletionsAdapter
    from backend.infrastructure.model_gateway.openai_responses import OpenAIResponsesAdapter

    runtime = runtime_at_public_entry(monkeypatch)
    sent = []

    def create(**kwargs):
        sent.append(kwargs)
        message = SimpleNamespace(content="建议保持规律饮食和训练。")
        return SimpleNamespace(output_text=message.content, choices=[SimpleNamespace(message=message)])

    client = SimpleNamespace(responses=SimpleNamespace(create=create),
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    adapter_type = OpenAIChatCompletionsAdapter if protocol == "chat" else OpenAIResponsesAdapter

    class Gateway(adapter_type):
        def plan_route(self, question):
            return PlannerRoute(intent="free_form_health_label")

    repository = SpyRepository()
    initial = {"meal_analysis": {"weekly_average_protein": 98, "protein_target_met": False},
               "weekly_report": {"title": "Weekly fitness report", "sections": [], "checklist": []},
               "report_week": "2026-W42", "private_unknown": {"body": "secret personal text"}}
    result = graph.run_fitlife_agent("How is my protein intake?", "owner", repository=repository,
        gateway=Gateway(client=client, model="test-model"), initial_tool_results=initial)
    assert len(sent) == 1
    raw = sent[0]["messages"][1]["content"] if protocol == "chat" else sent[0]["input"]
    payload = json.loads(raw)
    assert ChatInput.model_validate(payload).model_dump() == payload
    assert payload["tool_results"]["meal_analysis"]["weekly_average_protein"] == 98
    assert payload["tool_results"]["weekly_report"] == initial["weekly_report"]
    assert payload["tool_results"]["report_week"] == "2026-W42"
    assert payload["profile"]["daily_protein_target"] == 120
    assert payload["profile"]["allergies_or_restrictions"] == ["peanuts"]
    assert payload["intent"] == "free_form_health_label"
    assert "secret personal text" not in raw and "weight_kg" not in raw and "age" not in payload["profile"]
    assert repository.reads == [("profile", "owner")]
    events = runtime.repository.events(result["run_id"], "owner")
    completed = [event.step for event in events if event.event_type == "STEP_SUCCEEDED"]
    # Runtime and workflow both check input, followed by context and output review.
    assert completed.count("input_guard") == 2
    guards = [step for step in completed if step in {"input_guard", "context_guard", "safety_reviewer"}]
    assert guards == ["input_guard", "input_guard", "context_guard", "safety_reviewer"]


def test_typed_model_proposal_never_grants_domain_or_owner_permission():
    patch = FieldPatch(path="workout_plan.days.0.duration_min", old_value=20, new_value=30,
        reason="training", evidence_refs=[])
    repository = SpyRepository()
    reads = AuthorizedTaskReads(repository, "authenticated-owner", frozenset({"diet"}))
    assert patch.new_value == 30
    with pytest.raises(PermissionError, match="DOMAIN_NOT_AUTHORIZED"):
        reads.read_workouts()
    with pytest.raises(TypeError):
        reads.read_meals("model-selected-owner")
    reads.read_meals()
    assert repository.reads == [("meals", "authenticated-owner")]


def test_malicious_in_scope_classification_cannot_waive_original_risk_guard(monkeypatch):
    from backend.agent.safety import SafetyRefusal
    from backend.safety.business_scope import ScopeDecision
    runtime_at_public_entry(monkeypatch)
    monkeypatch.setattr("backend.safety.business_scope.decide_business_scope",
        lambda *args, **kwargs: ScopeDecision("in_scope", ("怎么安排训练",)))
    repository = SpyRepository()
    with pytest.raises(SafetyRefusal):
        graph.run_contextual_coach_action("today", "explain_today", None,
            "胸痛并且呼吸困难，如何继续训练？", "owner", repository=repository)
    assert repository.reads == []


def test_public_chat_mixed_scope_keeps_original_emergency_guard(monkeypatch):
    from backend.agent.safety import SafetyRefusal
    runtime_at_public_entry(monkeypatch)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("forbidden")
        raise AssertionError("Emergency input crossed a private/provider boundary")

    monkeypatch.setattr(graph, "get_fitness_repository", forbidden)
    monkeypatch.setattr(graph, "_resolve_gateway", forbidden)
    monkeypatch.setattr(graph, "_build_contextual_tool_context", forbidden)
    monkeypatch.setattr("backend.agent.workflow.retrieve_knowledge", forbidden)
    repository = SpyRepository()
    repository.read_profile = forbidden
    repository.read_meals = forbidden
    repository.read_workouts = forbidden
    with pytest.raises(SafetyRefusal):
        graph.run_fitlife_agent(
            "pick stocks, I have chest pain and difficulty breathing;另外单独问：how should I exercise",
            "owner", repository=repository)
    assert repository.reads == calls == []


def test_policy_modifier_repetition_has_a_bounded_watchdog():
    # A child contains a regression without blocking the suite's/event loop's
    # deadline machinery. Import overhead gets five seconds; the match itself
    # must handle both hostile inputs promptly. No live provider or storage.
    source = (
        "from backend.safety.business_scope import decide_business_scope; "
        "text = '\\u6211\\u7684' * 30 + '\\u653f\\u6cbb\\u8bad\\u7ec3'; "
        "assert decide_business_scope(text).allowed_subtasks == (); "
        "assert decide_business_scope(text[:-2]).allowed_subtasks == ()"
    )
    child = subprocess.run([sys.executable, "-c", source], cwd=Path(__file__).resolve().parents[2],
                           capture_output=True, text=True, timeout=5)
    assert child.returncode == 0, child.stderr
