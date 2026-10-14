"""Deterministic scoring: compare the expected final state against the actual one.

A missing field fails and is named; it is never coerced to None so that two absent
fields cannot be "equal". A keyword appearing anywhere is not success.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Score:
    passed: bool
    failed_fields: tuple[str, ...]


def score_state(expected: dict, actual: dict) -> Score:
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
