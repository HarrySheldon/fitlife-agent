"""L3 — context resolution: how is a matched term actually being used?

This is where a bare term match turns into a defensible judgement. A term inside a
negation, a hypothetical, a referral or a third-party statement is not a claim
about the user, so it must not be treated as one.

The class *semantics* and their precedence are code, because getting the order
wrong creates a safety hole. The phrases themselves come from the pack.
"""
from __future__ import annotations

from backend.safety.models import MAX_SEVERITY, CueTables, Modifier
from backend.safety.normalize import Normalized, left_window


def resolve_modifier(
    normalized: Normalized,
    clause,
    hit,
    cues: CueTables,
) -> Modifier:
    """Classify how ``hit`` is used, looking only inside its own clause."""
    window = left_window(normalized, clause, hit.span)

    # Pseudo-negation cancels a negation match. Without this, phrases such as
    # "不仅" and "无论" register as negations and hide an asserted claim.
    if any(phrase in window for phrase in cues.pseudo):
        return Modifier.pseudo

    if any(phrase in window for phrase in cues.referral):
        return Modifier.conditional_referral

    if any(phrase in window for phrase in cues.speculation):
        return Modifier.hypothetical

    # Deontic cues are checked before negation. "请不要自行停药" contains a
    # negation marker, but what it *is* is advice against stopping treatment:
    # the opposite of a harmful instruction. Reading it as a plain negation
    # would lose that distinction.
    if any(phrase in window for phrase in cues.deontic):
        return Modifier.prescriptive

    if any(phrase in window for phrase in cues.negation):
        return Modifier.negated

    if any(phrase in window for phrase in cues.third_party):
        return Modifier.third_party

    if any(marker in clause.text for marker in cues.definitional_markers):
        return Modifier.definitional

    return Modifier.asserted


def severity_for(hit, clause, modifier: Modifier, cues: CueTables) -> int:
    """Context-safe uses carry no actionable severity.

    An asserted clinical *instruction* is treated as maximally severe, because a
    directive to change medication is different in kind from mentioning it.
    """
    if modifier in {
        Modifier.negated,
        Modifier.prescriptive,
        Modifier.hypothetical,
        Modifier.conditional_referral,
        Modifier.third_party,
        Modifier.definitional,
        Modifier.pseudo,
    }:
        return 0
    if clause is not None and cues is not None:
        if any(marker in clause.text for marker in cues.imperative_markers):
            return MAX_SEVERITY
    return hit.default_severity