"""Both providers must receive the grounded request, not just the structured fake.

The provider-level sibling of the writer payload fix. A test that only drives a fake
structured gateway proves the workflow assembles a request; it does not prove either
real adapter sends it. That distinction is exactly what hid the context-guard bypass,
so the same assertion is made here for the grounded path.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from backend.agent.grounded_answer import GroundedAnswer
from backend.agent.workflow import FitLifeWorkflow
from backend.infrastructure.model_gateway.openai_chat_completions import (
    OpenAIChatCompletionsAdapter,
)
from backend.infrastructure.model_gateway.openai_responses import OpenAIResponsesAdapter


class _ResponsesClient:
    """Captures what `responses.parse` was asked for.

    The response mirrors the SDK shape the adapter reads: `output[*].content[*]` with
    `type == "output_text"` and a `parsed` value.
    """

    def __init__(self, parsed):
        self.parsed = parsed
        self.sent: list[dict] = []
        self.responses = self

    def parse(self, *, model, instructions, input, text_format, **kwargs):
        self.sent.append(
            {"model": model, "instructions": instructions, "input": input, "format": text_format}
        )
        parsed = self.parsed

        class _Item:
            type = "output_text"

            def __init__(self):
                self.parsed = parsed

        class _Output:
            type = "message"
            content = [_Item()]

        class _Response:
            output = [_Output()]

        return _Response()


class _ChatClient:
    def __init__(self, parsed):
        self.parsed = parsed
        self.sent: list[dict] = []
        self.chat = self
        self.completions = self

    def parse(self, *, model, messages, response_format, **kwargs):
        self.sent.append({"model": model, "messages": messages, "format": response_format})
        parsed = self.parsed

        class _Message:
            def __init__(self):
                self.parsed = parsed
                self.content = None

        class _Choice:
            message = _Message()

        class _Response:
            choices = [_Choice()]

        return _Response()


GROUNDED = {"blocks": [{"kind": "fact", "evidence_id": "protein_intake:2026-10-07"}]}


def _state():
    return {
        "user_query": "这周蛋白吃够了吗",
        "context_metadata": {"language": "zh-CN"},
        "intent": "meal_analysis",
        "profile": {"weight_kg": 70},
        "tool_results": {
            "meal_analysis": {
                "daily_totals": {"2026-10-07": {"calories": 1800, "protein": 70}},
                "weekly_average_protein": 70,
            }
        },
        "initial_tool_results_snapshot": {},
        "retrieved_docs": [],
        "validation_result": {},
    }


class _Context:
    def __init__(self):
        self.context_text = ""

    def consume_context(self, text):
        self.context_text += text

    def consume_output(self, text):
        pass

    async def tool(self, name, replay, operation):
        return operation()


def _run_with(adapter):
    workflow = FitLifeWorkflow(
        repository=None, gateway=None, grounding_mode="evidence", structured_gateway=adapter
    )
    state = _state()
    state["writer_payload"] = workflow.sanitize_writer_payload(state)
    return asyncio.run(workflow._writer(_Context(), state))


# --------------------------------------------------------------------------
# the responses provider
# --------------------------------------------------------------------------

def test_the_responses_provider_is_asked_for_the_grounded_structure():
    client = _ResponsesClient(GROUNDED)
    adapter = OpenAIResponsesAdapter(client=client, model="test-model")

    result = _run_with(adapter)

    assert client.sent, "the provider was never called"
    call = client.sent[0]
    assert call["format"] is GroundedAnswer
    sent = json.loads(call["input"])
    assert sent["user_query"] == "这周蛋白吃够了吗"
    assert any(item["metric"] == "protein_intake" for item in sent["evidence"])
    # The figure was rendered by this code, from the catalog.
    assert "70" in result["final_answer"]
    assert "2026-10-07" in result["final_answer"]


def test_the_responses_provider_cannot_state_a_number_of_its_own():
    """A block naming an id the catalog does not hold renders nothing."""
    client = _ResponsesClient({"blocks": [{"kind": "fact", "evidence_id": "made-up"}]})
    adapter = OpenAIResponsesAdapter(client=client, model="test-model")

    result = _run_with(adapter)

    assert "made-up" not in result["final_answer"]


# --------------------------------------------------------------------------
# the chat completions provider
# --------------------------------------------------------------------------

def test_the_chat_completions_provider_is_asked_for_the_grounded_structure():
    client = _ChatClient(GROUNDED)
    adapter = OpenAIChatCompletionsAdapter(client=client, model="test-model")

    result = _run_with(adapter)

    assert client.sent, "the provider was never called"
    call = client.sent[0]
    assert call["format"] is GroundedAnswer
    user_turn = next(m for m in call["messages"] if m["role"] == "user")
    sent = json.loads(user_turn["content"])
    assert any(item["scope"] == "2026-10-07" for item in sent["evidence"])
    assert "70" in result["final_answer"]


def test_the_system_turn_carries_the_grounded_instructions():
    client = _ChatClient(GROUNDED)
    adapter = OpenAIChatCompletionsAdapter(client=client, model="test-model")

    _run_with(adapter)

    system_turn = next(m for m in client.sent[0]["messages"] if m["role"] == "system")
    assert "do not state numbers yourself" in system_turn["content"]


# --------------------------------------------------------------------------
# the answer the review gate then sees
# --------------------------------------------------------------------------

def test_the_rendered_answer_is_what_the_review_step_receives():
    """The reviewer must judge the text that will actually be published."""
    client = _ResponsesClient(GROUNDED)
    adapter = OpenAIResponsesAdapter(client=client, model="test-model")
    workflow = FitLifeWorkflow(
        repository=None, gateway=None, grounding_mode="evidence", structured_gateway=adapter
    )
    state = _state()
    state["writer_payload"] = workflow.sanitize_writer_payload(state)

    written = asyncio.run(workflow._writer(_Context(), state))
    state.update(written)

    assert state["final_answer"] == written["final_answer"]
    assert "70" in state["final_answer"]
