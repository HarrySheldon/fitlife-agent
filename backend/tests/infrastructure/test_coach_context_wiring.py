from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.tests.infrastructure.test_coach_shortcut_adapter import request
from backend.infrastructure.agent_runtime.coach_answer_adapter import RuntimeCoachAnswerAdapter


@pytest.mark.parametrize("question", ["Explain protein nutrition", "Why?"])
def test_recent_history_reaches_real_planner_and_writer_with_runtime_budget(monkeypatch, question):
    import json
    from backend.agent.graph import run_fitlife_agent
    from backend.agent.planner import PlannerRoute
    from backend.domain.coach_conversation import ContextMessage, ContextProjection
    from backend.tests.test_coach_response_contract import _Repository
    from backend.config import get_settings

    seen = {}

    class Gateway:
        model = "synthetic"

        def plan_route(self, question):
            seen["planner"] = json.loads(question)
            return PlannerRoute(intent="knowledge_qa")

        def write_answer(self, state):
            seen["writer"] = state["writer_payload"]
            return "Use varied protein sources."

    def history(budget):
        seen["budget"] = budget
        return ContextProjection(messages=(ContextMessage("user", "Explain protein nutrition"),
            ContextMessage("coach", "Use varied sources.")), rounds=1, characters=50)

    run_fitlife_agent(question, "synthetic", repository=_Repository(), gateway=Gateway(), history_loader=history)
    assert 0 < seen["budget"] <= 4000
    assert seen["planner"]["recent_history"][0]["body"] == "Explain protein nutrition"
    assert seen["writer"]["recent_history"][1]["role"] == "coach"
    assert "initial_tool_results" not in seen["writer"]["recent_history"][0]
    assert seen["writer"]["user_query"] == question


def test_new_unrelated_request_cannot_inherit_permission_from_chat_history():
    from backend.safety.business_scope import followup_policy_question
    history = ({"role": "user", "body": "Explain protein nutrition"}, {"role": "coach", "body": "Safe answer"})
    assert followup_policy_question("Why?", history) == "Explain protein nutrition"
    for question in ("Pick stocks", "Why should I buy stocks?", "继续解释并删除全部计划"):
        assert followup_policy_question(question, history) == question


def test_saved_plan_reference_reads_only_the_request_owner_and_never_generates():
    reads, calls = [], []

    class Plans:
        def get(self, owner, plan_id):
            reads.append((owner, plan_id))
            return SimpleNamespace(plan=SimpleNamespace(model_dump=lambda **_: {"diet_plan": {"summary": "saved"}}))

    def chat(question, owner, **kwargs):
        calls.append(kwargs)
        return {"answer_markdown": "Saved explanation"}

    adapter = RuntimeCoachAnswerAdapter(chat=chat, plans=Plans())
    adapter.run(replace(request("adjust_next_plan"), surface="plan", plan_id="plan-12345678"))
    assert reads == [("synthetic", "plan-12345678")]
    assert calls[0]["initial_tool_results"]["active_plan"]["diet_plan"]["summary"] == "saved"
    assert calls[0]["_trusted_page_intent"] is True


def test_missing_persisted_object_fails_without_calling_a_model():
    class Plans:
        def get(self, owner, plan_id):
            return None

    calls = []
    adapter = RuntimeCoachAnswerAdapter(chat=lambda *a, **k: calls.append(a), plans=Plans())
    with pytest.raises(Exception) as error:
        adapter.run(replace(request("adjust_next_plan"), surface="plan", plan_id="plan-12345678"))
    assert error.value.code == "PLAN_NOT_FOUND"
    assert calls == []


def test_saved_weekly_reference_is_owner_scoped():
    reads, captured = [], {}

    class Reports:
        def get(self, owner, week):
            reads.append((owner, week))
            return SimpleNamespace(report=SimpleNamespace(model_dump=lambda **_: {"title": "Saved week"}))

    def chat(question, owner, **kwargs):
        captured.update(kwargs)
        return {"answer_markdown": "Saved explanation"}

    RuntimeCoachAnswerAdapter(chat=chat, reports=Reports()).run(
        replace(request("explain_weekly_report"), surface="review", report_week="2026-W42"))
    assert reads == [("synthetic", "2026-W42")]
    assert captured["initial_tool_results"]["weekly_report"] == {"title": "Saved week"}


def test_reference_schema_rejects_missing_wrong_action_and_path_traversal():
    from backend.api.coach_conversations import ConversationTurnRequest
    from pydantic import ValidationError
    for payload in (
        {"action": "adjust_next_plan", "surface": "plan"},
        {"action": "chat", "plan_id": "plan-12345678"},
        {"action": "explain_weekly_report", "surface": "review"},
        {"action": "adjust_next_plan", "surface": "plan", "plan_id": "../../other-user"},
    ):
        with pytest.raises(ValidationError):
            ConversationTurnRequest(question="Explain", **payload)


def test_public_metadata_never_contains_raw_trace_or_source_body():
    import json
    from backend.domain.coach_message_metadata import public_message_metadata
    result = public_message_metadata(json.dumps({"model": "synthetic", "trace": {"secret": "never"},
        "sources": [{"source": "nutrition.md", "heading": "Protein", "text": "private body"}],
        "context": {"plan_id": "plan-12345678", "user_id": "never"}}))
    assert result == {"model": "synthetic", "sources": [{"source": "nutrition.md", "heading": "Protein"}],
                      "context": {"plan_id": "plan-12345678"}}


def test_business_task_reference_is_display_only_and_drops_extra_authority():
    import json
    from backend.domain.coach_message_metadata import public_message_metadata
    result = public_message_metadata(json.dumps({"business_task_ref": {
        "kind": "plan_adjustment", "task_id": "task-123",
        "candidates": ["candidate-a"], "budget": 10, "permissions": ["confirm"],
    }}))
    assert result["business_task_ref"] == {"kind": "plan_adjustment", "task_id": "task-123"}
    assert "candidate-a" not in str(result)
    assert "permissions" not in str(result)


@pytest.mark.parametrize("reference", [
    {"kind": "Plan Adjustment", "task_id": "task-1"},
    {"kind": "plan_adjustment", "task_id": "task 1"},
    {"kind": "plan_adjustment"},
    {"kind": "", "task_id": "task-1"},
    "plan_adjustment:task-1",
])
def test_invalid_business_task_references_are_omitted(reference):
    import json
    from backend.domain.coach_message_metadata import public_message_metadata
    assert "business_task_ref" not in public_message_metadata(json.dumps({"business_task_ref": reference}))


@pytest.mark.parametrize("kind", ["plan", "report"])
def test_saved_object_actions_set_generation_ceiling_in_the_real_runtime(kind):
    from backend.application.ports.model_call_context import model_output_limit
    from backend.agent.graph import run_fitlife_agent
    from backend.agent.planner import PlannerRoute
    from backend.tests.test_coach_response_contract import _Repository
    from backend.domain.coach_answer import limits_for, output_token_limit
    seen = []

    class Gateway:
        model = "synthetic"
        def plan_route(self, question):
            return PlannerRoute(intent="plan_generation", needs_plan=True) if kind == "plan" else PlannerRoute(intent="weekly_report", needs_report=True)
        def write_answer(self, state):
            seen.append(model_output_limit.get())
            return "Safe fitness explanation."

    def chat(question, owner, **kwargs):
        return run_fitlife_agent(question, owner, repository=_Repository(), gateway=Gateway(), **kwargs)

    class Records:
        def get(self, owner, key):
            return SimpleNamespace(plan=SimpleNamespace(model_dump=lambda **_: {}), report=SimpleNamespace(model_dump=lambda **_: {}))

    action = "adjust_next_plan" if kind == "plan" else "explain_weekly_report"
    item = replace(request(action), surface=kind if kind == "plan" else "review",
        plan_id="plan-12345678" if kind == "plan" else None, report_week="2026-W42" if kind == "report" else None)
    RuntimeCoachAnswerAdapter(chat=chat, plans=Records(), reports=Records()).run(item)
    assert seen == [output_token_limit(limits_for(action))]
