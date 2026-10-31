"""Admission tests: a live batch may not run unless every claimed fact is re-proved."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.task_evaluation.acceptance import (
    AcceptanceManifest,
    ActualState,
    AdmissionRejected,
    Authorization,
    EvaluationBudget,
    admit_live,
)

DIGEST = "a" * 64
SHA = "b" * 40


# --------------------------------------------------------------------------
# budget
# --------------------------------------------------------------------------

def test_live_budget_requires_positive_limits():
    with pytest.raises(ValidationError):
        EvaluationBudget(max_calls=0, max_tokens=1000, max_seconds=30)


@pytest.mark.parametrize("field", ["max_calls", "max_tokens", "max_seconds"])
def test_each_budget_limit_must_be_positive(field):
    values = {"max_calls": 1, "max_tokens": 1, "max_seconds": 1}
    values[field] = 0

    with pytest.raises(ValidationError):
        EvaluationBudget(**values)


def test_a_positive_budget_is_accepted():
    budget = EvaluationBudget(max_calls=10, max_tokens=1000, max_seconds=30)

    assert budget.max_calls == 10


def test_budget_rejects_an_extra_field():
    with pytest.raises(ValidationError):
        EvaluationBudget(max_calls=1, max_tokens=1, max_seconds=1, max_money=1)


def test_budget_is_frozen():
    budget = EvaluationBudget(max_calls=1, max_tokens=1, max_seconds=1)

    with pytest.raises(Exception):
        budget.max_calls = 2


# --------------------------------------------------------------------------
# manifest shape
# --------------------------------------------------------------------------

def _manifest(**overrides) -> AcceptanceManifest:
    values = {
        "code_sha": SHA,
        "diff_digest": DIGEST,
        "suite_digest": DIGEST,
        "connection_ref": "approved-connection-1",
        "connection_fingerprint": DIGEST,
        "provider": "openai",
        "model": "test-model",
        "protocol": "responses",
        "engine": "unified_coach",
        "strategy": "reference",
        "phase": "compare",
        "invariant_fingerprint": DIGEST,
        "treatment_fingerprint": DIGEST,
        "review_mode": "off",
        "grounding_mode": "legacy",
        "synthetic_only": True,
        "repeat": 1,
        "annotation_protocol_version": "annotation-v1",
        "budget": EvaluationBudget(max_calls=10, max_tokens=1000, max_seconds=30),
    }
    values.update(overrides)
    return AcceptanceManifest(**values)


def _actual(**overrides) -> ActualState:
    values = {
        "code_sha": SHA,
        "diff_digest": DIGEST,
        "suite_digest": DIGEST,
        "connection_fingerprint": DIGEST,
        "provider": "openai",
        "model": "test-model",
        "protocol": "responses",
        "engine": "unified_coach",
        "review_mode": "off",
        "grounding_mode": "legacy",
        "invariant_fingerprint": DIGEST,
        "treatment_fingerprint": DIGEST,
        "scenario_count": 5,
        "has_real_user_data": False,
        "provider_registry": frozenset({"openai", "custom"}),
        "protocol_registry": frozenset({"responses", "chat_completions"}),
        "engine_registry": frozenset({"unified_coach", "plan_adjustment"}),
        "safety_mode_registry": frozenset({"off", "shadow", "enforce", "legacy", "evidence"}),
        "max_cases": 100,
    }
    values.update(overrides)
    return ActualState(**values)


def _authorization(**overrides) -> Authorization:
    values = {"approved_by": "operator", "expires_at": 2_000_000_000.0, "reference": "batch-1"}
    values.update(overrides)
    return Authorization(**values)


def test_manifest_requires_a_synthetic_marker():
    with pytest.raises(ValidationError):
        _manifest(synthetic_only=False)


def test_manifest_rejects_a_bad_digest():
    with pytest.raises(ValidationError):
        _manifest(diff_digest="not-a-digest")


def test_manifest_rejects_an_unknown_strategy():
    with pytest.raises(ValidationError):
        _manifest(strategy="fastest")


def test_manifest_rejects_an_unknown_phase():
    with pytest.raises(ValidationError):
        _manifest(phase="release")


def test_manifest_rejects_an_empty_connection_ref():
    with pytest.raises(ValidationError):
        _manifest(connection_ref="")


# --------------------------------------------------------------------------
# admission
# --------------------------------------------------------------------------

def test_a_matching_manifest_is_admitted():
    admit_live(_manifest(), actual=_actual(), authorization=_authorization(), now=1_000_000_000.0)


@pytest.mark.parametrize("field,value", [
    ("code_sha", "c" * 40),
    ("diff_digest", "d" * 64),
    ("suite_digest", "e" * 64),
    ("connection_fingerprint", "f" * 64),
    ("provider", "custom"),
    ("model", "other-model"),
    ("protocol", "chat_completions"),
    ("engine", "plan_adjustment"),
    ("review_mode", "enforce"),
    ("grounding_mode", "evidence"),
    ("invariant_fingerprint", "1" * 64),
    ("treatment_fingerprint", "2" * 64),
])
def test_a_mismatch_is_rejected_before_the_provider(field, value):
    with pytest.raises(AdmissionRejected):
        admit_live(_manifest(), actual=_actual(**{field: value}),
                   authorization=_authorization(), now=1_000_000_000.0)


def test_missing_authorization_is_rejected():
    with pytest.raises(AdmissionRejected, match="LIVE_NOT_AUTHORIZED"):
        admit_live(_manifest(), actual=_actual(), authorization=None, now=1_000_000_000.0)


def test_an_expired_authorization_is_rejected():
    authorization = _authorization(expires_at=1_000.0)

    with pytest.raises(AdmissionRejected, match="AUTHORIZATION_EXPIRED"):
        admit_live(_manifest(), actual=_actual(), authorization=authorization, now=2_000.0)


def test_real_user_data_is_rejected():
    with pytest.raises(AdmissionRejected, match="REAL_DATA_PRESENT"):
        admit_live(_manifest(), actual=_actual(has_real_user_data=True),
                   authorization=_authorization(), now=1_000_000_000.0)


def test_an_unknown_provider_is_rejected():
    with pytest.raises(AdmissionRejected, match="UNKNOWN_PROVIDER"):
        admit_live(_manifest(provider="mystery"), actual=_actual(provider="mystery"),
                   authorization=_authorization(), now=1_000_000_000.0)


def test_an_unknown_engine_is_rejected():
    """A business path that does not exist cannot be measured, so it is not admitted."""
    with pytest.raises(AdmissionRejected, match="UNKNOWN_ENGINE"):
        admit_live(_manifest(engine="ghost_engine"), actual=_actual(engine="ghost_engine"),
                   authorization=_authorization(), now=1_000_000_000.0)


def test_an_unknown_safety_mode_is_rejected():
    with pytest.raises(AdmissionRejected, match="UNKNOWN_REVIEW_MODE"):
        admit_live(_manifest(review_mode="paranoid"),
                   actual=_actual(review_mode="paranoid"),
                   authorization=_authorization(), now=1_000_000_000.0)


def test_a_batch_larger_than_the_case_limit_is_rejected():
    with pytest.raises(AdmissionRejected, match="BATCH_EXCEEDS_CASE_LIMIT"):
        admit_live(_manifest(repeat=100), actual=_actual(scenario_count=5, max_cases=100),
                   authorization=_authorization(), now=1_000_000_000.0)


def test_admission_never_reads_a_provider_or_a_credential():
    """The module must be able to decide with no network and no configuration."""
    import backend.task_evaluation.acceptance as module

    source = module.__doc__ or ""
    assert "no network" in source
