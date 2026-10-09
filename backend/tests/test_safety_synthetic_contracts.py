"""The offline synthetic suite: program-contract cases, not a measure of model safety.

These cases assert what the code does with a fixed input. A passing run here says the
renderer cannot be made to attach a number to the wrong meaning, and that the review
gate's plumbing behaves. It says nothing about whether a real model judges well, and
the report must not present one as the other.

The reviewer cases are run against a fixed fake provider so the review path is
exercised without a network call. Where the expected answer is "refuse", the assertion
is that the contract carries the refusal through, not that a model would produce it.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from backend.agent.grounded_answer import (
    NO_EVIDENCE_TEXT,
    GroundedAnswer,
    render_grounded_answer,
)
from backend.safety.evidence import build_evidence

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "safety"

REVIEWER_CASES = json.loads((FIXTURES / "reviewer_cases.json").read_text(encoding="utf-8"))["cases"]
GROUNDING_CASES = json.loads((FIXTURES / "grounding_cases.json").read_text(encoding="utf-8"))["cases"]


# --------------------------------------------------------------------------
# the fixtures themselves
# --------------------------------------------------------------------------

def test_the_reviewer_samples_meet_the_required_shape():
    assert len(REVIEWER_CASES) >= 60
    groups = {case["expected"] for case in REVIEWER_CASES}
    assert groups == {"allow", "refuse"}
    assert sum(1 for c in REVIEWER_CASES if c["expected"] == "refuse") >= 20
    assert sum(1 for c in REVIEWER_CASES if c["expected"] == "allow") >= 20
    for case in REVIEWER_CASES:
        assert case["id"] and case["question"] and case["draft"] and case["reason"]


def test_the_grounding_samples_meet_the_required_shape():
    assert len(GROUNDING_CASES) >= 40
    groups = {case["group"] for case in GROUNDING_CASES}
    assert {"correct_fact", "same_number_different_metric", "same_metric_different_day",
            "missing_records", "wrong_reference", "numeric_advice", "unknown_fields",
            "invalid_values"} <= groups
    for case in GROUNDING_CASES:
        assert case["id"] and "tool_results" in case and "blocks" in case


def test_the_fixtures_carry_no_real_user_data():
    """Synthetic by construction: no identifiers, no contact details, no records."""
    blob = json.dumps(REVIEWER_CASES + GROUNDING_CASES, ensure_ascii=False)
    for marker in ("@", "http://", "https://", "user_id", "13800"):
        assert marker not in blob


# --------------------------------------------------------------------------
# grounding cases
# --------------------------------------------------------------------------

def _render(case):
    catalog = build_evidence(case["tool_results"])
    answer = GroundedAnswer.model_validate({"blocks": case["blocks"]})
    return render_grounded_answer(answer, catalog)


@pytest.mark.parametrize("case", GROUNDING_CASES, ids=[c["id"] for c in GROUNDING_CASES])
def test_grounding_case(case):
    result = _render(case)

    for expected in case.get("must_contain", []):
        assert expected in result.text, f"{case['id']}: missing {expected!r} in {result.text!r}"
    for forbidden in case.get("must_not_contain", []):
        assert forbidden not in result.text, f"{case['id']}: {forbidden!r} leaked into {result.text!r}"


def test_every_grounding_case_produces_some_controlled_text():
    """Never an empty answer and never the raw model text."""
    for case in GROUNDING_CASES:
        result = _render(case)
        assert result.text.strip(), f"{case['id']} rendered nothing"
        assert result.text == result.text.strip()


def test_a_missing_record_never_becomes_a_zero():
    """The failure the catalog exists to prevent."""
    for case in GROUNDING_CASES:
        if case["group"] != "missing_records":
            continue
        catalog = build_evidence(case["tool_results"])
        for fact in catalog.values():
            assert fact.value != 0 or fact.metric not in {
                "energy_intake", "protein_intake", "carbohydrate_intake", "fat_intake"
            }


def test_a_body_weight_never_becomes_intake_evidence():
    for case in GROUNDING_CASES:
        catalog = build_evidence(case["tool_results"])
        assert all(fact.metric != "weight_kg" for fact in catalog.values())


# --------------------------------------------------------------------------
# reviewer cases, through the gate's plumbing with a fixed provider
# --------------------------------------------------------------------------

class _FixedModel:
    """Answers with the fixture's expectation, so the path is exercised offline."""

    def __init__(self, expected: str):
        self.expected = expected
        self.calls = 0

    def parse_structured(self, *, instructions, input_text, response_model):
        from backend.application.ports.structured_model_gateway import StructuredModelResult
        from backend.safety.review import ReviewVerdict

        self.calls += 1
        verdict = (
            ReviewVerdict(outcome="refuse", risk_category="harassment")
            if self.expected == "refuse"
            else ReviewVerdict(outcome="allow", risk_category="low")
        )
        return StructuredModelResult(output=verdict, model="fixed", usage={})


def _observe(case, monkeypatch):
    from backend.agent.semantic_review import collect_review

    class _Context:
        def __init__(self):
            self.tools = []

        def consume_context(self, text):
            pass

        def consume_output(self, text):
            pass

        async def tool(self, name, replay, operation):
            self.tools.append(name)
            return operation()

    import asyncio

    model = _FixedModel(case["expected"])
    observation = asyncio.run(
        collect_review(_Context(), model, "enforce", case["question"], case["draft"])
    )
    return observation, model


@pytest.mark.parametrize("case", REVIEWER_CASES, ids=[c["id"] for c in REVIEWER_CASES])
def test_reviewer_case_reaches_the_expected_observation(case, monkeypatch):
    observation, model = _observe(case, monkeypatch)

    assert model.calls == 1, "the review must be one call"
    assert observation.status == case["expected"]


def test_every_reviewer_case_makes_exactly_one_call():
    import asyncio

    from backend.agent.semantic_review import collect_review

    class _Context:
        def consume_context(self, text):
            pass

        def consume_output(self, text):
            pass

        async def tool(self, name, replay, operation):
            return operation()

    for case in REVIEWER_CASES:
        model = _FixedModel(case["expected"])
        asyncio.run(collect_review(_Context(), model, "enforce", case["question"], case["draft"]))
        assert model.calls == 1, case["id"]


def test_off_makes_no_call_for_any_case():
    import asyncio

    from backend.agent.semantic_review import collect_review

    class _Context:
        def consume_context(self, text):
            pass

        def consume_output(self, text):
            pass

        async def tool(self, name, replay, operation):
            raise AssertionError("off must not call the provider")

    for case in REVIEWER_CASES:
        observation = asyncio.run(
            collect_review(_Context(), _FixedModel(case["expected"]), "off",
                           case["question"], case["draft"])
        )
        assert observation.status == "disabled"


def test_shadow_records_a_refusal_without_carrying_it():
    """The observation holds the refusal; the reviewer the gate gets never refuses."""
    import asyncio

    from backend.agent.semantic_review import ObservationReviewer, collect_review

    class _Context:
        def consume_context(self, text):
            pass

        def consume_output(self, text):
            pass

        async def tool(self, name, replay, operation):
            return operation()

    refusals = [c for c in REVIEWER_CASES if c["expected"] == "refuse"]
    for case in refusals:
        observation = asyncio.run(
            collect_review(_Context(), _FixedModel("refuse"), "shadow",
                           case["question"], case["draft"])
        )
        assert observation.status == "refuse", case["id"]
        assert ObservationReviewer(observation, "shadow").review(
            case["question"], case["draft"]
        ).outcome == "allow"
