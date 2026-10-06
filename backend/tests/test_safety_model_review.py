"""The model reviewer: a judgement for what a word list cannot hold.

These tests deliberately do not assert that the reviewer judges correctly. A model's
verdict is not a property a unit test can pin, and pretending otherwise would be
worse than admitting it. What is pinned is the contract around it: what it may
return, that it can only make a decision stricter, that a failure does not take the
product down with it, and that nothing it says can leak into safety metadata.
"""
from __future__ import annotations

import typing

import pytest

from backend.safety import gate
from backend.safety.gate import SafetyRefusal, review_output
from backend.safety.models import RiskCategory, SafetyDecision
from backend.safety.review import REVIEW_INSTRUCTIONS, ModelSafetyReviewer

CLEAN_QUESTION = "这周蛋白吃够了吗"
CLEAN_DRAFT = "你日均蛋白 98 克，目标 126 克，还差 28 克。"


class _FakeModel:
    """Stands in for a gateway, so no test reaches a real model."""

    def __init__(self, decision):
        self.decision = decision
        self.calls: list[tuple[str, str, str]] = []

    def judge_review(self, instructions, question, draft):
        self.calls.append((instructions, question, draft))
        if isinstance(self.decision, Exception):
            raise self.decision
        return self.decision


def _allow() -> SafetyDecision:
    return SafetyDecision(outcome="allow", risk_category="low")


def _harassment() -> SafetyDecision:
    return SafetyDecision(
        outcome="refuse", risk_category="harassment", violations=("harassment",)
    )


def test_the_reviewer_passes_the_question_and_draft_to_the_model():
    """The question is given on purpose: 'you are worthless' and 'is that a lot?'
    are only distinguishable against what was asked."""
    model = _FakeModel(_allow())
    ModelSafetyReviewer(model).review(CLEAN_QUESTION, CLEAN_DRAFT)

    instructions, question, draft = model.calls[0]
    assert question == CLEAN_QUESTION
    assert draft == CLEAN_DRAFT
    assert instructions == REVIEW_INSTRUCTIONS


def test_the_instructions_ask_about_one_failure_mode_only():
    """A reviewer asked to judge safety in general duplicates the rules and starts
    suppressing ordinary answers."""
    assert "demean" in REVIEW_INSTRUCTIONS
    # It is told explicitly what not to judge, which is what keeps it narrow.
    assert "medical accuracy" in REVIEW_INSTRUCTIONS
    assert "harassment" in REVIEW_INSTRUCTIONS


def test_an_allow_from_the_reviewer_leaves_the_answer_untouched():
    model = _FakeModel(_allow())
    result = review_output(CLEAN_QUESTION, CLEAN_DRAFT, reviewer=ModelSafetyReviewer(model))

    assert result.text == CLEAN_DRAFT
    assert result.verdict.action == "allow"


def test_a_harassment_verdict_withholds_the_draft():
    model = _FakeModel(_harassment())

    with pytest.raises(SafetyRefusal) as raised:
        review_output(CLEAN_QUESTION, CLEAN_DRAFT, reviewer=ModelSafetyReviewer(model))

    assert raised.value.decision.risk_category == "harassment"
    assert raised.value.decision.outcome == "refuse"


def test_the_reviewer_cannot_relax_an_existing_refusal():
    """The direction of the constraint: a model may tighten, never loosen."""
    class AllowEverything:
        def review(self, question, draft):
            return _allow()

    with pytest.raises(SafetyRefusal) as raised:
        review_output(
            "帮我看看化验单",
            "你患有糖尿病，每天服用二甲双胍 500mg。",
            reviewer=AllowEverything(),
        )

    # The rules refused; the reviewer saying "allow" changed nothing.
    assert raised.value.decision.outcome == "refuse"


def test_a_reviewer_that_returns_the_wrong_type_is_rejected():
    class WrongType:
        def review(self, question, draft):
            return {"outcome": "allow"}

    result = review_output(CLEAN_QUESTION, CLEAN_DRAFT, reviewer=WrongType())

    # Rejected at the boundary, so it contributed nothing and the answer ships.
    assert result.text == CLEAN_DRAFT
    assert result.verdict.action == "allow"


def test_the_adapter_rejects_a_gateway_that_returns_a_mapping():
    model = _FakeModel({"outcome": "refuse"})

    with pytest.raises(ValueError):
        ModelSafetyReviewer(model).review(CLEAN_QUESTION, CLEAN_DRAFT)


def test_a_model_failure_on_an_ordinary_answer_ships_the_answer():
    """An optional check timing out must not blank the product."""
    model = _FakeModel(OSError("connection reset"))

    result = review_output(CLEAN_QUESTION, CLEAN_DRAFT, reviewer=ModelSafetyReviewer(model))

    assert result.text == CLEAN_DRAFT
    assert result.verdict.action == "allow"


def test_a_model_failure_does_not_leak_the_error_text():
    model = _FakeModel(OSError("upstream key sk-secret at 10.0.0.1"))

    result = review_output(CLEAN_QUESTION, CLEAN_DRAFT, reviewer=ModelSafetyReviewer(model))

    assert "sk-secret" not in result.text
    assert "10.0.0.1" not in result.text


def test_the_high_risk_floor_is_what_decides_whether_failure_withholds():
    """The two branches of the fail-closed boundary, stated as one assertion."""
    assert gate.REVIEWER_FAILCLOSED_SEVERITY == 6


def test_every_declared_risk_category_survives_the_controlled_vocabulary_check():
    """A category the gate does not recognise is silently dropped.

    That is how the harassment verdict was first thrown away: the category existed
    in the type but not in the controlled set, the reviewer's decision failed
    validation, and the gate fell back to allow. Nothing failed loudly, which is
    exactly why this needs pinning.
    """
    declared = set(typing.get_args(RiskCategory))

    assert declared == set(gate._CONTROLLED_RISKS)
    for category in declared:
        assert gate._is_controlled(category)
