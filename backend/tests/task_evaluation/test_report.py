"""Report tests: metrics must not hide the failures that produce them."""
from __future__ import annotations

import pytest

from backend.task_evaluation.report import (
    RunRecord,
    build_report,
    cost_per_success,
    render_json,
    render_markdown,
)


def test_cost_per_success_divides_total_by_successes():
    """Cost is shared across all runs, so one success among two carries both costs."""
    assert cost_per_success(total_tokens=30, successes=1) == 30.0
    assert cost_per_success(total_tokens=100, successes=4) == 25.0


def test_mixed_modes_have_no_combined_cost_and_legacy_failure_coverage():
    records = [RunRecord("mock", "a", 1, True, 10, "m", "r"),
               RunRecord("live", "b", 1, False, 90, None, None)]
    report = build_report(records)
    assert report.total_tokens is None
    assert report.cost_per_success is None
    assert report.groups["live"].coverage == {"failed": 1}


def test_partial_unknown_versions_and_tokens_are_not_masked():
    records = [RunRecord("mock", "a", 1, True, 10, "m", "r"),
               RunRecord("mock", "b", 1, False, None, None, None, error_class="worker_error")]
    report = build_report(records)
    assert report.model_version == report.rule_version == "unknown"
    assert report.groups["mock"].known_total_tokens == 10
    assert report.groups["mock"].unknown_token_count == 1


def test_cost_per_success_is_null_without_successes():
    assert cost_per_success(total_tokens=30, successes=0) is None


def test_cost_per_success_is_null_without_successes_and_keeps_total():
    """A zero denominator is null, not zero; the cost is still reported elsewhere."""
    record = RunRecord(
        mode="mock", case_id="a", version=1, success=False,
        total_tokens=30, model=None, rule_version=None,
    )
    report = build_report([record])
    assert report.total_tokens == 30
    assert report.cost_per_success is None


def test_missing_token_count_is_unknown_not_zero():
    record = RunRecord(
        mode="mock", case_id="a", version=1, success=True,
        total_tokens=None, model="m", rule_version="r",
    )
    report = build_report([record])
    assert report.total_tokens is None
    assert report.cost_per_success is None


def test_unknown_model_and_rule_version_are_recorded_as_unknown():
    record = RunRecord(
        mode="mock", case_id="a", version=1, success=True,
        total_tokens=10, model=None, rule_version=None,
    )
    report = build_report([record])
    assert report.model_version == "unknown"
    assert report.rule_version == "unknown"


def test_mock_and_live_are_reported_separately():
    mock = RunRecord(mode="mock", case_id="a", version=1, success=True,
                     total_tokens=10, model="m", rule_version="r")
    live = RunRecord(mode="live", case_id="b", version=1, success=False,
                     total_tokens=90, model="m", rule_version="r")
    report = build_report([mock, live])

    assert report.groups["mock"].successes == 1
    assert report.groups["live"].successes == 0
    # Mock and live must never be merged into one success rate.
    assert report.groups["mock"].cost_per_success == 10.0
    assert report.groups["live"].cost_per_success is None


def test_render_markdown_keeps_failure_timing_separate():
    records = [
        RunRecord(mode="mock", case_id="a", version=1, success=True, total_tokens=1,
                  model="m", rule_version="r", processing_ms=100),
        RunRecord(mode="mock", case_id="b", version=1, success=False, total_tokens=1,
                  model="m", rule_version="r", processing_ms=900),
    ]
    markdown = render_markdown(build_report(records))

    assert "成功" in markdown
    assert "失败" in markdown
    # A sample of two must never advertise a P95 advantage.
    assert "P95" not in markdown


def test_render_json_groups_modes_and_keeps_provenance():
    import json

    mock = RunRecord(mode="mock", case_id="a", version=1, success=True, total_tokens=10,
                     model="m", rule_version="r", git_sha="abc123", config_fingerprint="fp",
                     processing_ms=100, calls=2, retries=1)
    live = RunRecord(mode="live", case_id="b", version=1, success=False, total_tokens=90,
                     model="m", rule_version="r", error_class="unexpected_status")
    payload = json.loads(render_json(build_report([mock, live])))

    # Modes stay separated in the machine-readable output too.
    assert set(payload["groups"]) == {"mock", "live"}
    assert payload["groups"]["mock"]["successes"] == 1
    assert payload["groups"]["live"]["successes"] == 0
    record = next(r for r in payload["records"] if r["case_id"] == "a")
    assert record["git_sha"] == "abc123"
    assert record["config_fingerprint"] == "fp"
    assert record["retries"] == 1


def test_mixed_modes_do_not_merge_into_one_version():
    """Mock and live sharing a model name must still not roll up as one result."""
    mock = RunRecord(mode="mock", case_id="a", version=1, success=True, total_tokens=1,
                     model="m", rule_version="r")
    live = RunRecord(mode="live", case_id="b", version=1, success=True, total_tokens=1,
                     model="m", rule_version="r")
    report = build_report([mock, live])
    assert report.model_version == "unknown"
    assert report.rule_version == "unknown"
