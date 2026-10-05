"""Facade over the safety gate.

The gate lives in :mod:`backend.safety`, split into detection, decision and
presentation, with its rule content in versioned packs under
``backend/data/safety/``. This module keeps the long-standing import path and
service shape stable for its consumers: ``runtime``, ``workflow`` and
``structured_workflow``.
"""
from __future__ import annotations

from backend.safety import check_input as _check_input
from backend.safety import review_output as _review_output
from backend.safety.gate import MAX_QUESTION_CHARS, SAFETY_RULE_VERSION, SafetyRefusal
from backend.safety.models import (
    ControlledDisclaimer,
    Modifier,
    RiskCategory,
    SafetyDecision,
    Verdict,
)


class SafetyReviewer:
    """Extension point.

    An extra reviewer may only tighten a decision: the deterministic gate has
    already run by the time it is consulted, and its result cannot be relaxed.
    """

    def review(self, question: str, draft: str) -> SafetyDecision: ...


_OUTCOME_BY_ACTION = {
    "allow": "allow",
    # Observation ships the draft untouched, so at the service level it is an allow
    # that happens to carry a record of what was noticed.
    "annotate": "allow",
    "disclose": "rewrite",
    "mask": "rewrite",
    "rewrite": "rewrite",  # fail-closed projection used when review is unavailable
    "refuse": "refuse",
    "escalate": "refuse",
}

# Concerns that map onto a controlled service-level category.
_CATEGORY_BY_CONCERN: dict[str, RiskCategory] = {
    "emergency": "emergency",
    "self_harm": "self_harm",
    "clinical_territory": "medical",
    "extreme_diet": "extreme_diet",
    "calorie_restriction": "extreme_diet",
    "disordered_eating": "extreme_diet",
    "dangerous_training": "dangerous_training",
    "out_of_scope": "out_of_scope",
    # A stated measurement the data does not support. Not a safety category: the
    # answer is usable, the reader just needs to know what to distrust.
    "ungrounded": "low",
    # Reported when an extension review could not run; the deterministic gate
    # still withheld the draft, so this is a category and not an action.
    "review_unavailable": "review_unavailable",
}


def decision_for(verdict: Verdict) -> SafetyDecision:
    """Project a gate verdict onto the service-level decision."""
    outcome = _OUTCOME_BY_ACTION[verdict.action]
    category: RiskCategory = "low"
    if verdict.concern in _CATEGORY_BY_CONCERN:
        category = _CATEGORY_BY_CONCERN[verdict.concern]
    elif verdict.severity > 6:
        category = "input_limit"
    return SafetyDecision(
        outcome=outcome,
        risk_category=category,
        violations=() if category == "low" else (category,),
        detected=verdict.detected,
        filtered=verdict.filtered,
        severity=verdict.severity,
        modifiers=tuple(modifier.value for modifier in verdict.modifiers),
        evidence_spans=verdict.evidence_spans,
    )


def check_input(question: str) -> SafetyDecision:
    """Refuse a question that must not reach a model. Raises on refusal."""
    return decision_for(_check_input(question))


def review_output(
    question: str,
    draft: str,
    *,
    reviewer: SafetyReviewer | None = None,
    supporting_values: tuple[float, ...] | None = None,
) -> tuple[str, SafetyDecision]:
    """Review a draft answer; returns the text to ship and the decision.

    ``supporting_values`` are the figures the answer was allowed to state. Passing
    them turns on the groundedness check; omitting them leaves it off.
    """
    result = _review_output(
        question, draft, reviewer=reviewer, supporting_values=supporting_values
    )
    return result.text, decision_for(result.verdict)


__all__ = [
    "ControlledDisclaimer",
    "MAX_QUESTION_CHARS",
    "Modifier",
    "RiskCategory",
    "SAFETY_RULE_VERSION",
    "SafetyDecision",
    "SafetyRefusal",
    "SafetyReviewer",
    "Verdict",
    "check_input",
    "decision_for",
    "review_output",
]
