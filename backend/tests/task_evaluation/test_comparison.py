"""Paired comparison only compares what is actually comparable.

A percentage is withheld rather than invented: no positive baseline means no
reduction, a cold reference is never paired with a warm optimized run, and a
case that exists on only one side is reported as unmatched instead of being
deleted from the denominator.
"""
import pytest

from backend.task_evaluation.comparison import (
    pair_records,
    paired_summary,
    reduction_percent,
)
from backend.task_evaluation.report import RunRecord

INVARIANT = "a" * 64


def _record(case_id="perf-zh", *, strategy="reference", repeat=0, cache="cold",
            invariant=INVARIANT, success=True, ms=100.0, tokens=100, mode="mock"):
    return RunRecord(
        mode=mode, case_id=case_id, version=1, success=success,
        total_tokens=tokens, model="synthetic", rule_version="fitlife-safety-v1",
        processing_ms=ms, strategy=strategy, repeat_index=repeat,
        cache_state=cache, invariant_fingerprint=invariant,
    )


def test_reduction_requires_positive_baseline():
    assert reduction_percent(100.0, 75.0) == 25.0
    assert reduction_percent(0.0, 1.0) is None
    assert reduction_percent(None, 1.0) is None
    assert reduction_percent(100.0, None) is None


def test_regression_is_reported_as_a_negative_reduction():
    assert reduction_percent(100.0, 120.0) == -20.0


def test_a_different_engine_or_data_version_is_not_paired():
    result = pair_records([_record()], [_record(strategy="optimized", invariant="b" * 64)])
    assert result.matched == ()
    assert [rejection.reason for rejection in result.rejected] == ["invariant_mismatch"]


def test_a_cold_reference_is_not_paired_with_a_warm_optimized_run():
    result = pair_records([_record()], [_record(strategy="optimized", cache="warm")])
    assert result.matched == ()
    assert [rejection.reason for rejection in result.rejected] == ["cache_state_mismatch"]


def test_cases_present_on_only_one_side_are_reported_not_dropped():
    result = pair_records(
        [_record("a"), _record("b")],
        [_record("a", strategy="optimized")],
    )
    assert len(result.matched) == 1
    assert [record.case_id for record in result.unmatched] == ["b"]


def test_repeats_pair_by_index_rather_than_by_position():
    reference = [_record(repeat=0, ms=100.0), _record(repeat=1, ms=200.0)]
    optimized = [_record(strategy="optimized", repeat=1, ms=150.0),
                 _record(strategy="optimized", repeat=0, ms=80.0)]

    result = pair_records(reference, optimized)

    assert len(result.matched) == 2
    assert {(left.repeat_index, right.repeat_index) for left, right in result.matched} == {(0, 0), (1, 1)}


def test_two_runs_with_the_same_pairing_key_are_rejected_as_ambiguous():
    duplicate = [_record(), _record()]
    result = pair_records(duplicate, [_record(strategy="optimized")])
    assert result.matched == ()
    assert "duplicate_reference" in [rejection.reason for rejection in result.rejected]


def test_mock_and_live_records_are_never_paired():
    result = pair_records([_record()], [_record(strategy="optimized", mode="live")])
    assert result.matched == ()
    assert [rejection.reason for rejection in result.rejected] == ["mode_mismatch"]


def test_failures_count_toward_cost_but_not_toward_latency():
    reference = [_record(success=False, ms=50.0), _record("ok", ms=100.0)]
    optimized = [_record(strategy="optimized", success=False, ms=10.0),
                 _record("ok", strategy="optimized", ms=75.0)]

    summary = paired_summary(pair_records(reference, optimized))

    assert summary.matched_count == 2
    assert summary.success_pairs == 1
    assert summary.failure_pairs == 1
    assert summary.latency_reduction_percent == 25.0


def test_no_successful_pair_means_no_latency_claim():
    reference = [_record(success=False, ms=50.0)]
    optimized = [_record(strategy="optimized", success=False, ms=10.0)]

    summary = paired_summary(pair_records(reference, optimized))

    assert summary.latency_reduction_percent is None
    assert summary.failure_pairs == 1


def test_unknown_tokens_on_either_side_keep_the_reduction_unknown():
    reference = [_record(tokens=None)]
    optimized = [_record(strategy="optimized", tokens=50)]

    summary = paired_summary(pair_records(reference, optimized))

    assert summary.token_reduction_percent is None
