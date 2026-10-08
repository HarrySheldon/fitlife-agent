"""The grounded path through the production writer.

The plan's requirement is specific: test what the two providers actually receive, not
merely that the state holds an evidence catalog. A check that runs on one payload while
the adapter sends another was the bug in the context guard, and it would be the same
mistake here.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from backend.agent.grounded_answer import NO_EVIDENCE_TEXT, GroundedAnswer
from backend.agent.workflow import FitLifeWorkflow
from backend.application.ports.structured_model_gateway import StructuredModelResult


class _StructuredGateway:
    model = "test-model"

    def __init__(self, answer=None, error=None):
        self.answer = answer or GroundedAnswer.model_validate(
            {"blocks": [{"kind": "fact", "evidence_id": "protein_intake:2026-10-07"}]}
        )
        self.error = error
        self.calls: list[dict] = []

    def parse_structured(self, *, instructions, input_text, response_model):
        self.calls.append(
            {"instructions": instructions, "input_text": input_text, "model": response_model}
        )
        if self.error is not None:
            raise self.error
        return StructuredModelResult(output=self.answer, model="test-model", usage={})


class _Context:
    def __init__(self):
        self.context_text = ""

    def consume_context(self, text):
        self.context_text += text

    def consume_output(self, text):
        pass

    async def tool(self, name, replay, operation):
        return operation()


def _state(intent="meal_analysis"):
    return {
        "user_query": "这周蛋白吃够了吗",
        "context_metadata": {"language": "zh-CN"},
        "intent": intent,
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


def _run(intent="meal_analysis", grounding="evidence", gateway=None, state=None):
    workflow = FitLifeWorkflow(
        repository=None, gateway=None, grounding_mode=grounding, structured_gateway=gateway
    )
    state = state or _state(intent)
    state["writer_payload"] = workflow.sanitize_writer_payload(state)
    context = _Context()
    result = asyncio.run(workflow._writer(context, state))
    return result, context, workflow


# --------------------------------------------------------------------------
# the two intents and the two modes
# --------------------------------------------------------------------------

@pytest.mark.parametrize("intent", ["meal_analysis", "workout_analysis"])
def test_evidence_mode_asks_for_the_grounded_structure(intent):
    gateway = _StructuredGateway()

    result, _context, _workflow = _run(intent=intent, gateway=gateway)

    assert gateway.calls, "the structured gateway was never called"
    assert gateway.calls[0]["model"] is GroundedAnswer
    assert result["final_answer"]


def test_legacy_mode_keeps_using_the_free_form_writer():
    """An intent without a catalog must not be silently switched."""
    calls = []

    class _FreeForm:
        provider = "t"
        model = "m"

        def write_answer(self, state):
            calls.append(True)
            return "你日均蛋白 98 克。"

    workflow = FitLifeWorkflow(repository=None, gateway=_FreeForm(), grounding_mode="evidence",
                               structured_gateway=_StructuredGateway())
    state = _state(intent="chat")
    state["writer_payload"] = workflow.sanitize_writer_payload(state)

    result = asyncio.run(workflow._writer(_Context(), state))

    assert calls == [True]
    assert "98" in result["final_answer"]


def test_legacy_grounding_mode_does_not_use_the_catalog():
    calls = []

    class _FreeForm:
        provider = "t"
        model = "m"

        def write_answer(self, state):
            calls.append(True)
            return "x"

    workflow = FitLifeWorkflow(repository=None, gateway=_FreeForm(), grounding_mode="legacy",
                               structured_gateway=_StructuredGateway())
    state = _state()
    state["writer_payload"] = workflow.sanitize_writer_payload(state)

    asyncio.run(workflow._writer(_Context(), state))

    assert calls == [True]


# --------------------------------------------------------------------------
# what the provider receives
# --------------------------------------------------------------------------

def test_the_provider_receives_the_question_the_context_and_the_catalog():
    """Asserted on the request, not on the state."""
    gateway = _StructuredGateway()

    _run(gateway=gateway)

    sent = json.loads(gateway.calls[0]["input_text"])
    assert sent["user_query"] == "这周蛋白吃够了吗"
    assert sent["context"]["user_query"] == "这周蛋白吃够了吗"
    ids = {item["id"] for item in sent["evidence"]}
    assert "protein_intake:2026-10-07" in ids
    # The catalog carries metric, unit and scope - not a bare number.
    entry = next(item for item in sent["evidence"] if item["id"] == "protein_intake:2026-10-07")
    assert entry["metric"] == "protein_intake"
    assert entry["unit"] == "g"
    assert entry["scope"] == "2026-10-07"


def test_the_catalog_does_not_carry_a_body_weight():
    """A weight must not be available for the model to cite as intake."""
    gateway = _StructuredGateway()

    _run(gateway=gateway)

    sent = json.loads(gateway.calls[0]["input_text"])
    assert all("weight" not in item["id"] for item in sent["evidence"])
    assert all(item["metric"] != "weight_kg" for item in sent["evidence"])


def test_the_instructions_forbid_stating_numbers():
    gateway = _StructuredGateway()

    _run(gateway=gateway)

    instructions = gateway.calls[0]["instructions"]
    assert "do not state numbers yourself" in instructions
    assert "discarded" in instructions


# --------------------------------------------------------------------------
# failure modes
# --------------------------------------------------------------------------

def test_evidence_mode_without_a_structured_gateway_fails_closed():
    """Falling back to free text would publish the prose this mode distrusts."""
    from backend.domain.errors import ApplicationError

    with pytest.raises(ApplicationError) as raised:
        _run(gateway=None)

    assert raised.value.code == "CONFIGURATION_INVALID"


def test_an_empty_catalog_still_produces_a_controlled_answer():
    gateway = _StructuredGateway(
        answer=GroundedAnswer.model_validate(
            {"blocks": [{"kind": "explanation", "text": "记录还不够。"}]}
        )
    )
    state = _state()
    state["tool_results"] = {"meal_analysis": {"daily_totals": {}}}

    result, _context, _workflow = _run(gateway=gateway, state=state)

    assert result["final_answer"] == NO_EVIDENCE_TEXT
