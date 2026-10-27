"""Deterministic scoring: compare the expected final state against the actual one.

A missing field fails and is named; it is never coerced to None so that two absent
fields cannot be "equal". A keyword appearing anywhere is not success.

Nor is prose. A model that says "两个部分都已通过校验" has said nothing a validator
confirmed, so a scenario that scored on that sentence would be measuring fluency
rather than the product. The keys below are refused outright.
"""
from __future__ import annotations

from dataclasses import dataclass

# Keys that only ever hold model text or user text.
_PROSE_KEYS = frozenset({
    "answer", "answer_markdown", "body", "message", "text", "reason", "summary",
    "question", "instructions", "plan_document", "constraints",
})


@dataclass(frozen=True)
class Score:
    passed: bool
    failed_fields: tuple[str, ...]


def score_state(expected: dict, actual: dict) -> Score:
    prose = _PROSE_KEYS & set(expected)
    if prose:
        # Not a product result: a scenario is trying to score on text, and the
        # only honest answer is to refuse the scenario.
        raise ValueError(f"Scenario may not score on prose: {sorted(prose)}")
    failed = tuple(
        key for key, value in expected.items()
        if key not in actual or not _exact_equal(value, actual[key])
    )
    return Score(not failed, failed)


def _exact_equal(expected, actual) -> bool:
    if type(expected) is not type(actual):
        return False
    if isinstance(expected, dict):
        return expected.keys() == actual.keys() and all(
            _exact_equal(value, actual[key]) for key, value in expected.items()
        )
    if isinstance(expected, (list, tuple)):
        return len(expected) == len(actual) and all(
            _exact_equal(left, right) for left, right in zip(expected, actual)
        )
    return expected == actual
