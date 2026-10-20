"""C0: the answer language is carried as controlled metadata, not inferred.

The bug this pins down: `explain_today` with no free question builds an English
internal prompt. The old writer instruction told the model to follow the language of
`user_query`, so a Chinese account got an English answer, and the deterministic
labels were Chinese regardless. These tests drive the real adapter and inspect the
bytes it hands to the provider.
"""
from __future__ import annotations

import json

import pytest

from backend.agent import graph as agent_graph
from backend.agent.planner import PlannerRoute
from backend.agent.workflow import FitLifeWorkflow
from backend.application.ports.model_call_context import model_output_limit
from backend.domain.coach_answer import limits_for, output_token_limit
from backend.domain.user_preferences import UserPreferences
from backend.infrastructure.model_gateway.openai_chat_completions import (
    OpenAIChatCompletionsAdapter,
)
from backend.infrastructure.model_gateway.openai_responses import OpenAIResponsesAdapter
from backend.tools.data_access import DEFAULT_PROFILE


class _Repository:
    """Empty records; the contextual loader expects frames, not lists."""

    def read_profile(self, user_id=None):
        return DEFAULT_PROFILE

    def read_meals(self, user_id=None):
        import pandas as pd

        return pd.DataFrame(columns=["date", "meal", "food", "amount", "calories",
                                     "protein", "carbs", "fat"])

    def read_workouts(self, user_id=None):
        import pandas as pd

        return pd.DataFrame(columns=["date", "type", "exercise", "muscle_group",
                                     "sets", "reps", "weight", "duration_min"])


class _ResponsesClient:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.responses = self

    def create(self, *, input, **kwargs):
        self.sent.append(input)

        class _Response:
            output_text = "ok"

        return _Response()


class _ChatClient:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.chat = self
        self.completions = self

    def create(self, *, messages, **kwargs):
        self.sent.append(next(m["content"] for m in messages if m["role"] == "user"))

        class _Choice:
            class message:
                content = "ok"

        class _Response:
            choices = [_Choice()]

        return _Response()


class _Gateway:
    """A fake planner plus the real writer adapter, so the wire bytes are real."""

    provider = "openai"
    model = "test-model"

    def __init__(self, adapter) -> None:
        self.adapter = adapter

    def plan_route(self, question):
        return PlannerRoute(intent="meal_analysis", needs_meal_analysis=True)

    def write_answer(self, state):
        return self.adapter.write_answer(state)


def _run_explain_today(monkeypatch, adapter, *, preferences, language=None, mode=None):
    monkeypatch.setattr(agent_graph, "_resolve_gateway", lambda user_id: _Gateway(adapter))
    agent_graph.run_contextual_coach_action(
        surface="today",
        action="explain_today",
        date="2026-10-18",
        question=None,
        user_id="user-a",
        repository=_Repository(),
        preferences=preferences,
        language=language,
        answer_mode=mode,
    )


def test_a_chinese_account_is_told_to_answer_in_chinese(monkeypatch):
    """The English internal prompt must not become the answer language."""
    client = _ResponsesClient()
    _run_explain_today(
        monkeypatch,
        OpenAIResponsesAdapter(client=client, model="test-model"),
        preferences=UserPreferences(language="zh-CN"),
    )

    assert client.sent, "the provider was never called"
    payload = json.loads(client.sent[0])
    assert payload["answer_language"] == "zh-CN"
    # The prompt really is English; that is what used to leak into the answer.
    assert payload["user_query"].startswith("Explain today")


def test_the_ui_locale_does_not_decide_the_answer_language(monkeypatch):
    """An English UI with an explicit Chinese request answers in Chinese."""
    client = _ResponsesClient()
    _run_explain_today(
        monkeypatch,
        OpenAIResponsesAdapter(client=client, model="test-model"),
        preferences=UserPreferences(language="en-US"),
        language="zh-CN",
    )

    payload = json.loads(client.sent[0])
    assert payload["answer_language"] == "zh-CN"
    assert payload["context_metadata"]["language"] == "en-US"


def test_an_explicit_request_covers_only_this_turn(monkeypatch):
    client = _ResponsesClient()
    adapter = OpenAIResponsesAdapter(client=client, model="test-model")
    preferences = UserPreferences(language="zh-CN")

    _run_explain_today(monkeypatch, adapter, preferences=preferences, language="en-US")
    _run_explain_today(monkeypatch, adapter, preferences=preferences)

    assert json.loads(client.sent[0])["answer_language"] == "en-US"
    assert json.loads(client.sent[1])["answer_language"] == "zh-CN"


def test_the_chat_completions_wire_carries_the_same_metadata(monkeypatch):
    client = _ChatClient()
    _run_explain_today(
        monkeypatch,
        OpenAIChatCompletionsAdapter(client=client, model="test-model"),
        preferences=UserPreferences(language="zh-CN"),
        mode="detailed",
    )

    payload = json.loads(client.sent[0])
    assert payload["answer_language"] == "zh-CN"
    assert payload["answer_mode"] == "detailed"


# --------------------------------------------------------------------------
# the generation ceiling follows the registered action
# --------------------------------------------------------------------------

class _LimitSpy:
    provider = "test"
    model = "test-model"

    def __init__(self) -> None:
        self.seen: list[int | None] = []

    def plan_route(self, question):
        return PlannerRoute(intent="meal_analysis", needs_meal_analysis=True)

    def write_answer(self, state):
        self.seen.append(model_output_limit.get())
        return "ok"


def _writer_for(action, mode):
    import asyncio

    spy = _LimitSpy()
    workflow = FitLifeWorkflow(
        repository=_Repository(), gateway=spy, answer_mode=mode, coach_action=action
    )
    state = {
        "user_query": "这周蛋白吃够了吗",
        "context_metadata": {"language": "zh-CN"},
        "intent": "meal_analysis",
        "profile": {},
        "tool_results": {},
        "retrieved_docs": [],
        "validation_result": {},
        "answer_language": "zh-CN",
        "answer_mode": mode,
        "coach_action": action,
    }

    class _Context:
        def consume_context(self, text):
            pass

        def consume_output(self, text):
            pass

        async def tool(self, name, replay, operation):
            return operation()

    state["writer_payload"] = workflow.sanitize_writer_payload(state)
    asyncio.run(workflow._writer(_Context(), state))
    return spy.seen[0]


def test_the_brief_ceiling_comes_from_the_registered_action():
    assert _writer_for("explain_today", "brief") == output_token_limit(
        limits_for("explain_today", "brief")
    )


def test_detailed_mode_raises_the_ceiling():
    brief = _writer_for("explain_today", "brief")
    detailed = _writer_for("explain_today", "detailed")
    assert detailed is not None and brief is not None
    assert detailed > brief


def test_the_ceiling_is_restored_after_the_writer_returns():
    """A leaked context value would silently bound the next call in the same task."""
    _writer_for("explain_today", "brief")
    assert model_output_limit.get() is None


def test_an_unregistered_run_is_not_bounded_by_a_card_rule():
    """Chat and plan generation are not cards; a card's allowance would truncate them."""
    assert _writer_for(None, "brief") is None


# --------------------------------------------------------------------------
# each protocol maps the ceiling to its own parameter
# --------------------------------------------------------------------------

class _KwargClient:
    """Captures the keyword arguments the adapter passes to the provider."""

    def __init__(self) -> None:
        self.kwargs: list[dict] = []
        self.responses = self
        self.chat = self
        self.completions = self

    def create(self, *, input=None, messages=None, **kwargs):
        self.kwargs.append(kwargs)
        if messages is not None:

            class _Choice:
                class message:
                    content = "ok"

            class _Response:
                choices = [_Choice()]

            return _Response()

        class _Response:
            output_text = "ok"

        return _Response()


def _writer_state():
    return {"user_query": "q", "intent": "knowledge_qa", "context_metadata": {"language": "zh-CN"}}


def test_the_responses_wire_maps_the_ceiling_to_max_output_tokens():
    client = _KwargClient()
    adapter = OpenAIResponsesAdapter(client=client, model="m")
    token = model_output_limit.set(1234)
    try:
        adapter.write_answer(_writer_state())
    finally:
        model_output_limit.reset(token)

    assert client.kwargs[0]["max_output_tokens"] == 1234


def test_the_chat_wire_maps_the_ceiling_to_max_completion_tokens():
    client = _KwargClient()
    adapter = OpenAIChatCompletionsAdapter(client=client, model="m")
    token = model_output_limit.set(1234)
    try:
        adapter.write_answer(_writer_state())
    finally:
        model_output_limit.reset(token)

    assert client.kwargs[0]["max_completion_tokens"] == 1234


def test_no_ceiling_is_sent_when_none_is_set():
    client = _KwargClient()
    OpenAIResponsesAdapter(client=client, model="m").write_answer(_writer_state())

    assert "max_output_tokens" not in client.kwargs[0]


# --------------------------------------------------------------------------
# the fixed product-boundary copy follows the same language rule
# --------------------------------------------------------------------------

def _boundary_answer(language, *, scope="out_of_scope", needs_clarification=False):
    """Drive the fixed boundary copy directly; the scope classifier needs a model."""
    import asyncio

    from backend.agent.contracts import AgentCommand
    from backend.agent.runtime import RuntimeContext
    from backend.agent.tasks.boundary_workflow import BoundaryWorkflow
    from backend.safety.business_scope import ScopeDecision

    workflow = BoundaryWorkflow(
        ScopeDecision(scope, (), refusal_code="OUT_OF_SCOPE",
                      needs_clarification=needs_clarification),
        language=language,
    )
    command = AgentCommand(operation="coach_action", question="帮我选股", user_id="user-a")
    return asyncio.run(workflow.execute(command, RuntimeContext())).answer_markdown


def test_the_refusal_copy_follows_the_answer_language():
    zh = _boundary_answer("zh-CN")
    en = _boundary_answer("en-US")

    assert "无法提供" in zh
    assert "cannot help" in en
    assert not any("\u4e00" <= ch <= "\u9fff" for ch in en)


def test_the_clarification_copy_follows_the_answer_language():
    zh = _boundary_answer("zh-CN", scope="unclear", needs_clarification=True)
    en = _boundary_answer("en-US", scope="unclear", needs_clarification=True)

    assert "请单独说明" in zh
    assert "on its own" in en
