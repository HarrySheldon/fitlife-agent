"""Acceptance needs more than "the optimized side was faster".

Four things are checked here, and each of them is a way the number could be
wrong while still looking good:

* a percentile whose method is not stated cannot be reproduced;
* a cost per success computed from successful runs only is not a cost;
* a sample too small for an interval must say so instead of inventing one;
* a faster run that violated a hard constraint, or that changed the engine
  under test, is a different experiment and is refused rather than reported.
"""
import pytest

from backend.task_evaluation.comparison import (
    MINIMUM_INTERVAL_SAMPLE,
    PERCENTILE_METHOD,
    bootstrap_median_interval,
    distribution,
    pair_records,
    paired_summary,
    percentile,
    quality_gate,
)
from backend.task_evaluation.report import RunRecord

INVARIANT = "a" * 64


def test_latency_interval_uses_the_same_mean_ratio_as_the_point_estimate():
    left = [record(str(i), ms=100) for i in range(8)]
    right = [record(str(i), strategy='optimized', ms=50 if i < 7 else 1000) for i in range(8)]
    summary = paired_summary(pair(left=left, right=right))
    assert summary.latency_reduction_percent == -68.75
    assert summary.latency_reduction_interval.low < 0


def record(case_id="plan-task-training-only", *, strategy="reference", repeat=0,
           success=True, ms=1000.0, tokens=1000, candidate_ms=None,
           failed_fields=(), cleanup="done", details=None, invariant=INVARIANT,
           cache="cold", mode="mock"):
    return RunRecord(
        mode=mode, case_id=case_id, version=1, success=success,
        total_tokens=tokens, model="synthetic", rule_version="fitlife-safety-v1",
        processing_ms=ms, candidate_ms=candidate_ms, strategy=strategy,
        repeat_index=repeat, cache_state=cache, invariant_fingerprint=invariant,
        details={
            "failed_fields": list(failed_fields),
            "cleanup_status": cleanup,
            "candidate_reason": ("validated_candidate" if candidate_ms is not None
                                 else "no_timed_candidate"),
            "attempts_incomplete": 0,
            **(details or {}),
        },
    )


def pair(*, left=None, right=None):
    left = left if left is not None else [record()]
    right = right if right is not None else [record(strategy="optimized")]
    return pair_records(left, right)


# -- percentiles -------------------------------------------------------


def test_the_percentile_method_is_declared():
    assert PERCENTILE_METHOD == "nearest-rank"


def test_nearest_rank_takes_a_value_that_was_actually_observed():
    values = [10.0, 20.0, 30.0, 40.0]
    # ceil(0.5 * 4) = 2 -> the second smallest, not the mean of 20 and 30.
    assert percentile(values, 0.50) == 20.0
    # ceil(0.95 * 4) = 4 -> the largest.
    assert percentile(values, 0.95) == 40.0
    assert percentile([], 0.5) is None


def test_the_distribution_reports_its_range_and_size():
    spread = distribution([10.0, 20.0, 30.0, 40.0])
    assert spread.count == 4
    assert (spread.minimum, spread.maximum) == (10.0, 40.0)
    assert (spread.p50, spread.p95) == (20.0, 40.0)
    assert spread.method == PERCENTILE_METHOD


def test_a_missing_measurement_does_not_become_a_zero():
    spread = distribution([None, 20.0, None])
    assert spread.count == 1
    assert (spread.minimum, spread.maximum, spread.p50) == (20.0, 20.0, 20.0)


# -- intervals ---------------------------------------------------------


def test_a_sample_below_the_minimum_gets_a_reason_not_an_interval():
    interval = bootstrap_median_interval([1.0, 2.0, 3.0])
    assert interval.low is None and interval.high is None
    assert interval.reason == "insufficient_sample"
    assert len([1.0, 2.0, 3.0]) < MINIMUM_INTERVAL_SAMPLE


def test_the_interval_is_reproducible_for_a_fixed_seed():
    values = [float(index) for index in range(MINIMUM_INTERVAL_SAMPLE)]
    first = bootstrap_median_interval(values, seed=7)
    second = bootstrap_median_interval(values, seed=7)
    assert (first.low, first.high) == (second.low, second.high)
    assert first.low <= first.high
    assert first.reason is None


# -- cost --------------------------------------------------------------


def test_cost_per_success_counts_the_failures():
    # 2 successes and 2 failures; the cost of a success includes what the
    # failures consumed, otherwise "cheaper" just means "more was dropped".
    reference = [record("a"), record("b"),
                 record("c", success=False), record("d", success=False)]
    optimized = [record("a", strategy="optimized", tokens=400),
                 record("b", strategy="optimized", tokens=400),
                 record("c", strategy="optimized", success=False, tokens=400),
                 record("d", strategy="optimized", success=False, tokens=400)]

    summary = paired_summary(pair(left=reference, right=optimized))

    assert summary.reference_cost_per_success == 2000.0
    assert summary.optimized_cost_per_success == 800.0
    assert summary.failure_pairs == 2


def test_unknown_usage_makes_the_cost_unknown_rather_than_lower():
    reference = [record("a"), record("b", tokens=None)]
    optimized = [record("a", strategy="optimized", tokens=100),
                 record("b", strategy="optimized", tokens=100)]

    summary = paired_summary(pair(left=reference, right=optimized))

    assert summary.reference_cost_per_success is None
    # 200 tokens over 2 successes, not 100: the denominator is successes, the
    # numerator is everything that was spent.
    assert summary.optimized_cost_per_success == 100.0


def test_no_success_means_no_cost_per_success():
    reference = [record(success=False)]
    optimized = [record(strategy="optimized", success=False)]

    summary = paired_summary(pair(left=reference, right=optimized))

    assert summary.reference_cost_per_success is None
    assert summary.optimized_cost_per_success is None


# -- what is counted as a pair ----------------------------------------


def test_the_counts_are_reported_separately():
    reference = [record("a"), record("b"), record("c")]
    optimized = [record("a", strategy="optimized"),
                 record("b", strategy="optimized", invariant="b" * 64)]

    summary = paired_summary(pair(left=reference, right=optimized))

    assert summary.paired_count == 1
    assert summary.rejected_pairs == 1
    assert summary.unmatched_count == 1


def test_a_faster_run_under_a_different_engine_is_not_accepted():
    reference = [record(ms=1000.0)]
    optimized = [record(strategy="optimized", ms=100.0, invariant="b" * 64)]

    result = pair(left=reference, right=optimized)
    summary = paired_summary(result)

    assert summary.latency_reduction_percent is None
    gate = quality_gate(result, summary)
    assert gate.passed is False
    assert "no_comparable_pair" in gate.reasons


def test_a_safety_violation_fails_the_gate_even_when_the_run_is_faster():
    # The optimized side activated a plan the scenario declared must not be
    # activated. Being 10x faster does not make that acceptable.
    reference = [record(ms=1000.0)]
    optimized = [record(strategy="optimized", ms=100.0, success=False,
                        failed_fields=("plan_activations",))]

    result = pair(left=reference, right=optimized)
    summary = paired_summary(result)
    gate = quality_gate(result, summary)

    assert summary.latency_reduction_percent is None  # the pair is not a success pair
    assert gate.passed is False
    assert [violation.category for violation in gate.violations] == ["invalid_activations"]
    assert gate.violations[0].fact == "plan_activations"
    assert "safety_violation" in gate.reasons


@pytest.mark.parametrize("fact,category", [
    ("coach_unapproved_answers", "unauthorized_access"),
    ("confirmed_meals", "duplicate_writes"),
    ("plan_activations", "invalid_activations"),
])
def test_every_safety_category_is_named(fact, category):
    result = pair(right=[record(strategy="optimized", success=False,
                                failed_fields=(fact,))])
    gate = quality_gate(result, paired_summary(result))
    assert [violation.category for violation in gate.violations] == [category]


def test_an_unrelated_failed_field_is_not_a_safety_violation():
    result = pair(right=[record(strategy="optimized", success=False,
                                failed_fields=("message_count",))])
    gate = quality_gate(result, paired_summary(result))
    assert gate.violations == ()
    assert "quality_regression" in gate.reasons


def test_a_case_that_passed_in_reference_and_failed_in_optimized_is_a_regression():
    result = pair(left=[record("a", ms=100.0)],
                  right=[record("a", strategy="optimized", ms=90.0, success=False,
                                failed_fields=("plan_rounds",))])
    gate = quality_gate(result, paired_summary(result))

    assert gate.passed is False
    assert gate.regressions == ("a",)
    assert "quality_regression" in gate.reasons


def test_the_gate_names_every_category_even_when_they_are_all_zero():
    result = pair()
    gate = quality_gate(result, paired_summary(result))
    assert gate.passed is True
    assert gate.as_record()["violations"] == {
        "unauthorized_access": 0, "duplicate_writes": 0, "invalid_activations": 0}


def test_a_missing_side_keeps_the_case_visible():
    result = pair(left=[record("a"), record("b")],
                  right=[record("a", strategy="optimized")])
    gate = quality_gate(result, paired_summary(result))
    assert [record.case_id for record in result.unmatched] == ["b"]
    assert "unmatched_case" in gate.reasons
    assert gate.passed is False


# -- candidate timing --------------------------------------------------


def test_candidate_time_only_counts_a_verified_candidate():
    result = pair(
        left=[record("a", candidate_ms=500.0), record("b", candidate_ms=None)],
        right=[record("a", strategy="optimized", candidate_ms=300.0),
               record("b", strategy="optimized", candidate_ms=None)],
    )
    summary = paired_summary(result)

    assert summary.reference_candidate.count == 1
    assert summary.optimized_candidate.count == 1
    assert summary.reference_candidate.p50 == 500.0


# -- measurement coverage ---------------------------------------------


def test_unknown_measurement_and_cleanup_are_reported_separately_from_safety():
    reference = [record("a"), record("b", tokens=None),
                 record("c", cleanup="failed", success=False)]
    optimized = [record("a", strategy="optimized")]

    summary = paired_summary(pair(left=reference, right=optimized))

    assert summary.coverage.runs == 4
    assert summary.coverage.unknown_usage == 1
    assert summary.coverage.cleanup_failed == 1
    assert summary.coverage.unknown_usage_rate == 0.25
    # Coverage problems are reported, they are not folded into the safety counts.
    assert quality_gate(pair(left=reference, right=optimized), summary).violations == ()


def test_the_point_estimate_carries_an_interval_or_says_why_not():
    # One pair is not a sample: the summary must not present a bare percentage
    # as if it were established.
    single = paired_summary(pair())
    assert single.latency_reduction_interval.reason == "insufficient_sample"

    reference = [record(f"c{index}", ms=1000.0 + index)
                 for index in range(MINIMUM_INTERVAL_SAMPLE)]
    optimized = [record(f"c{index}", strategy="optimized", ms=800.0 + index)
                 for index in range(MINIMUM_INTERVAL_SAMPLE)]
    enough = paired_summary(pair(left=reference, right=optimized))

    assert enough.latency_reduction_interval.reason is None
    assert enough.latency_reduction_interval.low <= enough.latency_reduction_interval.high
    # The interval brackets the point estimate it belongs to.
    assert (enough.latency_reduction_interval.low
            <= enough.latency_reduction_percent
            <= enough.latency_reduction_interval.high)
