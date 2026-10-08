"""When the extra review fails, the deterministic decision must still be carried out.

The gate decides an action - mask, disclose, refuse, escalate - and then, optionally,
consults a reviewer. The reviewer may only tighten. A reviewer that cannot run has
said nothing, so the action the rules already chose must still happen.

This was broken: the failure branch returned the draft directly, skipping the action
dispatch entirely. The reviewer contributed nothing and the deterministic decision
was dropped with it. Worse for the low-severity branches, which are exactly where
`disclose` and `mask` are used.

The claims are fixed with monkeypatch rather than vocabulary, so these test the
disposition flow itself and do not depend on whether the phrase list happens to match.
"""
from __future__ import annotations

import pytest

from backend.safety import gate
from backend.safety.models import SafetyDecision, Verdict


class BrokenReviewer:
    def review(self, question, draft):
        raise OSError("review service unavailable")


def _disposition(action: str, severity: int = 3) -> Verdict:
    return Verdict(
        detected=True, filtered=True, action=action, severity=severity,
        concern="clinical_territory", modifiers=(), evidence_spans=((0, 2),),
    )


def _fixed_decisions(monkeypatch, verdict):
    """First call decides the question, second the draft.

    The iterator is built once and consumed by the patched callable. Building it
    inside the lambda would hand out a fresh iterator per call, so the first verdict
    would come back every time and the disposition under test would never be reached.
    """
    decisions = iter((
        (Verdict(False, False, "allow", 0, None, (), ()), None),
        (verdict, "generic"),
    ))
    monkeypatch.setattr(gate, "_decide", lambda *args: next(decisions))


@pytest.mark.parametrize("action", ["mask", "disclose"])
def test_review_failure_preserves_a_low_severity_action(monkeypatch, action):
    """The action still happens, and the text it produces still ships."""
    _fixed_decisions(monkeypatch, _disposition(action))

    result = gate.review_output("普通问题", "原始草稿内容足够长", reviewer=BrokenReviewer())

    assert result.verdict.action == action
    assert result.text != "原始草稿内容足够长"


@pytest.mark.parametrize("action", ["refuse", "escalate"])
def test_review_failure_preserves_a_withholding_action(monkeypatch, action):
    _fixed_decisions(monkeypatch, _disposition(action))

    with pytest.raises(gate.SafetyRefusal) as raised:
        gate.review_output("普通问题", "原始草稿", reviewer=BrokenReviewer())

    assert raised.value.verdict.action == action


@pytest.mark.parametrize("action", ["allow", "annotate"])
def test_review_failure_ships_the_draft_when_the_action_is_to_ship(monkeypatch, action):
    _fixed_decisions(monkeypatch, _disposition(action))

    result = gate.review_output("普通问题", "原始草稿", reviewer=BrokenReviewer())

    assert result.verdict.action == action
    assert result.text == "原始草稿"


def test_review_failure_still_withholds_at_the_high_severity_floor(monkeypatch):
    """Where the rules already found high risk, no review means no shipment."""
    _fixed_decisions(monkeypatch, _disposition("disclose", severity=6))

    with pytest.raises(gate.SafetyRefusal) as raised:
        gate.review_output("普通问题", "原始草稿", reviewer=BrokenReviewer())

    assert raised.value.decision.risk_category == "review_unavailable"


def test_review_failure_does_not_leak_the_error(monkeypatch):
    _fixed_decisions(monkeypatch, _disposition("allow"))

    class Leaky:
        def review(self, question, draft):
            raise OSError("upstream key sk-secret at 10.0.0.1")

    result = gate.review_output("普通问题", "原始草稿", reviewer=Leaky())

    assert "sk-secret" not in result.text
    assert "10.0.0.1" not in result.text


def test_an_unsupported_reviewer_outcome_is_not_treated_as_allow():
    """`rewrite` is not a reviewer decision; accepting it would silently ship."""
    class Rewriting:
        def review(self, question, draft):
            return SafetyDecision.model_construct(
                outcome="rewrite", risk_category="low", violations=()
            )

    result = gate.review_output("普通问题", "原始草稿", reviewer=Rewriting())

    # Invalid, so the reviewer contributed nothing and the rules' answer stands.
    assert result.verdict.action == "allow"
    assert result.text == "原始草稿"


def test_the_reviewer_can_still_tighten_when_it_does_run():
    """The fix must not make the reviewer toothless."""
    class Refusing:
        def review(self, question, draft):
            return SafetyDecision(
                outcome="refuse", risk_category="harassment", violations=("harassment",)
            )

    with pytest.raises(gate.SafetyRefusal) as raised:
        gate.review_output("普通问题", "原始草稿", reviewer=Refusing())

    assert raised.value.decision.risk_category == "harassment"
