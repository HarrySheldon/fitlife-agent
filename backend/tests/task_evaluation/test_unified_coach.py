from pathlib import Path
import time
import pytest
from backend.task_evaluation.contracts import Suite
from backend.task_evaluation.runner import run_isolated_scenario, _observe_response, CaseError


def suite():
    return Suite.model_validate_json((Path(__file__).parents[2] / 'task_evaluation/scenarios/unified_coach.json').read_text(encoding='utf-8'))


def test_suite_has_24_distinct_bounded_scenarios():
    cases = suite().scenarios
    assert len(cases) >= 24
    assert all('unified_coach' in case.requires for case in cases)
    assert all(case.expected.get('coach_unapproved_answers') == 0 for case in cases)


def test_only_controlled_trace_counts_can_be_observed():
    assert _observe_response({'data': {'receipt': {'trace': {'tool_denials': 1}}}},
        {'denials': 'data.receipt.trace.tool_denials'}) == {'denials': 1}
    with pytest.raises(CaseError):
        _observe_response({'data': {'receipt': {'trace': {'question': 'private'}}}},
            {'question': 'data.receipt.trace.question'})


@pytest.mark.parametrize('name', ['unified-original-chest', 'unified-path-escape', 'unified-complete-plan'])
def test_network_blocked_worker_replays_real_publication(name):
    scenario = next(item for item in suite().scenarios if item.id == name)
    result = run_isolated_scenario(scenario, deadline=time.monotonic() + 60)
    assert result.status == 'passed', result
    assert result.observed['confirmed_meals'] == 0
    assert result.observed['confirmed_workouts'] == 0
