"""Measurement honesty: a missing number is unknown, never zero.

The evaluation report is only useful if it can be wrong. Every assertion here
exists to stop an unmeasured quantity from being silently rendered as ``0`` or
as a mock character estimate.
"""
from types import SimpleNamespace

import pytest

from backend.task_evaluation.measurements import (
    AttemptKind,
    AttemptLedger,
    AttemptState,
    UsageMeasurement,
    config_fingerprints,
    summarize_attempts,
)


def test_unknown_usage_is_not_zero_or_mock_estimate():
    measured = UsageMeasurement(source='unknown', input_tokens=None,
        output_tokens=None, cached_input_tokens=None)
    assert measured.total_tokens is None
    assert measured.source != 'mock_estimate'


def test_provider_zero_is_measured_and_distinct_from_unknown():
    zero = UsageMeasurement(source='provider', input_tokens=0, output_tokens=0,
                            cached_input_tokens=None)
    assert zero.total_tokens == 0
    assert zero.total_tokens is not None


def test_cached_input_is_a_subset_and_never_added_to_the_total():
    measured = UsageMeasurement(source='provider', input_tokens=100,
                                output_tokens=20, cached_input_tokens=60)
    assert measured.total_tokens == 120


@pytest.mark.parametrize('value', [-1, 1.0, True, '3', 2.5])
def test_usage_rejects_values_that_cannot_be_a_token_count(value):
    with pytest.raises(ValueError):
        UsageMeasurement(source='provider', input_tokens=value,
                         output_tokens=0, cached_input_tokens=None)


def test_usage_rejects_an_unregistered_source():
    with pytest.raises(ValueError):
        UsageMeasurement(source='estimated', input_tokens=1, output_tokens=1,
                         cached_input_tokens=None)


def test_unknown_usage_cannot_carry_a_partial_number():
    with pytest.raises(ValueError):
        UsageMeasurement(source='unknown', input_tokens=5, output_tokens=None,
                         cached_input_tokens=None)
    with pytest.raises(ValueError):
        UsageMeasurement(source='provider', input_tokens=None, output_tokens=5,
                         cached_input_tokens=None)


def test_cached_input_cannot_exceed_input():
    with pytest.raises(ValueError):
        UsageMeasurement(source='provider', input_tokens=10, output_tokens=1,
                         cached_input_tokens=11)


def test_ledger_closes_every_started_attempt():
    ledger = AttemptLedger(clock=lambda: 0.0)
    done = ledger.open(AttemptKind.PHYSICAL_HANDLER, tool='fitness.query')
    ledger.complete(done, UsageMeasurement(source='unknown', input_tokens=None,
                                           output_tokens=None, cached_input_tokens=None))
    ledger.open(AttemptKind.PHYSICAL_MODEL, tool='write_answer_model')

    summary = ledger.close_unfinished(AttemptState.INCOMPLETE)

    assert summary.started == 2
    assert summary.completed == 1
    assert summary.incomplete == 1
    assert summary.failed == 0
    assert summary.unknown_usage == 1


def test_ledger_marks_cleaned_up_cancellation_separately_from_incomplete():
    ledger = AttemptLedger(clock=lambda: 0.0)
    ledger.open(AttemptKind.PHYSICAL_HANDLER, tool='fitness.query')

    summary = ledger.close_unfinished(AttemptState.CANCELLED)

    assert summary.cancelled == 1
    assert summary.incomplete == 0
    assert summary.started == 1


def test_attempt_identifiers_are_generated_and_unique():
    ledger = AttemptLedger(clock=lambda: 0.0)
    first = ledger.open(AttemptKind.PHYSICAL_HANDLER, tool='fitness.query')
    second = ledger.open(AttemptKind.PHYSICAL_HANDLER, tool='fitness.query')
    assert first != second
    assert len(first) == 32 and int(first, 16) >= 0


def test_ledger_rejects_an_unknown_attempt_identifier():
    ledger = AttemptLedger(clock=lambda: 0.0)
    with pytest.raises(KeyError):
        ledger.complete('0' * 32, UsageMeasurement(source='unknown', input_tokens=None,
                                                   output_tokens=None, cached_input_tokens=None))


def test_ledger_rejects_an_unregistered_kind_or_state():
    ledger = AttemptLedger(clock=lambda: 0.0)
    with pytest.raises(ValueError):
        ledger.open('physical_guess')
    ledger.open(AttemptKind.PHYSICAL_HANDLER)
    with pytest.raises(ValueError):
        ledger.close_unfinished('done')


def test_summary_keeps_known_tokens_apart_from_unknown_ones():
    ledger = AttemptLedger(clock=lambda: 0.0)
    measured = ledger.open(AttemptKind.PHYSICAL_MODEL, tool='plan_route_model')
    ledger.complete(measured, UsageMeasurement(source='provider', input_tokens=7,
                                               output_tokens=3, cached_input_tokens=0))
    unmeasured = ledger.open(AttemptKind.PHYSICAL_MODEL, tool='write_answer_model')
    ledger.complete(unmeasured, UsageMeasurement(source='unknown', input_tokens=None,
                                                 output_tokens=None, cached_input_tokens=None))

    summary = summarize_attempts(ledger.records())

    # The known sum never absorbs the unknown one, and the unknown count is
    # reported next to it so a reader cannot mistake 10 for the real cost.
    assert summary.known_total_tokens == 10
    assert summary.unknown_usage == 1
    assert summary.completed == 2


def test_treatment_change_does_not_look_like_a_different_task():
    baseline = SimpleNamespace(coach_agent_mode='unified',
                               task_execution_strategy='reference',
                               context_policy_version='v1')
    optimized = SimpleNamespace(coach_agent_mode='unified',
                                task_execution_strategy='optimized',
                                context_policy_version='v1')

    left = config_fingerprints(baseline)
    right = config_fingerprints(optimized)

    assert left['invariant_config_fingerprint'] == right['invariant_config_fingerprint']
    assert left['treatment_config_fingerprint'] != right['treatment_config_fingerprint']


@pytest.mark.parametrize('field,value', [
    ('coach_agent_mode', 'legacy'),
    ('coach_conversations_enabled', True),
    ('plan_adjustment_tasks_enabled', True),
    ('plan_storage_mode', 'sqlite'),
    ('safety_review_mode', 'enforce'),
])
def test_invariant_change_invalidates_the_fingerprint(field, value):
    baseline = SimpleNamespace(coach_agent_mode='unified',
                               task_execution_strategy='reference',
                               coach_conversations_enabled=False,
                               plan_adjustment_tasks_enabled=False,
                               plan_storage_mode='file',
                               safety_review_mode='off')
    changed = SimpleNamespace(**{**vars(baseline), field: value})

    assert (config_fingerprints(baseline)['invariant_config_fingerprint']
            != config_fingerprints(changed)['invariant_config_fingerprint'])
