"""Tests for Fold-in #6: Pass^k vs Pass@k, trajectory first-error attribution & report compatibility."""
from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3

import pytest

from backend.task_evaluation.attribution import attribute_first_error
from backend.task_evaluation.comparison import compute_pass_k
from backend.task_evaluation.observation import observe_database
from backend.task_evaluation.report import RunRecord, build_report, render_json, render_markdown


def test_compute_pass_k_distinguishes_flaky_pass_at_k_from_pass_pow_k():
    # Case A: passes 1 of 3 tries -> Pass@3 = 1.0, Pass^3 = 0.0 (flaky!).
    # Case B: passes all 3 of 3 tries -> Pass@3 = 1.0, Pass^3 = 1.0 (reliable).
    records = [
        RunRecord("mock", "flaky", 1, True, 10, "m", "r", repeat_index=0),
        RunRecord("mock", "flaky", 1, False, 10, "m", "r", repeat_index=1, error_class="failed"),
        RunRecord("mock", "flaky", 1, False, 10, "m", "r", repeat_index=2, error_class="failed"),
        RunRecord("mock", "steady", 1, True, 10, "m", "r", repeat_index=0),
        RunRecord("mock", "steady", 1, True, 10, "m", "r", repeat_index=1),
        RunRecord("mock", "steady", 1, True, 10, "m", "r", repeat_index=2),
    ]
    summary = compute_pass_k(records)
    assert summary.k == 3
    assert summary.cases_evaluated == 2
    assert summary.pass_at_k == pytest.approx(1.0)
    assert summary.pass_pow_k == pytest.approx(0.5)
    assert summary.per_case["flaky:v1"]["pass_at_k"] == 1.0
    assert summary.per_case["flaky:v1"]["pass_pow_k"] == 0.0
    assert summary.per_case["steady:v1"]["pass_pow_k"] == 1.0


def test_attribute_first_error_picks_earliest_failing_step_over_downstream_errors():
    events = [
        {"seq": 1, "event_type": "STEP_STARTED", "step": "retrieve_knowledge", "step_index": 0},
        {"seq": 3, "event_type": "STEP_FAILED", "step": "output_writer", "step_index": 2, "error_type": "safety", "error_code": "SAFETY_REFUSAL"},
        {"seq": 2, "event_type": "TOOL_FINISHED", "step": "tool_food_lookup", "step_index": 1, "agent_tool": "catalog.search_foods", "outcome": "failed", "error_code": "MODEL_TIMEOUT"},
    ]
    failed = RunRecord(
        "mock",
        "c-tool-first",
        1,
        False,
        None,
        "m",
        "r",
        error_class="failed",
        details={"run_ids": ["run-123"], "events": events},
    )
    attr = attribute_first_error(failed)
    assert attr is not None
    assert attr.error_category == "tool_execution"
    assert attr.step_index == 1
    assert attr.step_name == "tool_food_lookup"
    assert attr.run_id == "run-123"

    passing = RunRecord("mock", "c-ok", 1, True, 10, "m", "r")
    assert attribute_first_error(passing) is None


def test_attribute_first_error_falls_back_to_record_error_class_and_failed_fields():
    timeout_record = RunRecord(
        "mock",
        "c-timeout",
        1,
        False,
        None,
        "m",
        "r",
        error_class="timed_out",
        details={"failed_fields": ["turn_not_terminal"]},
    )
    attr_timeout = attribute_first_error(timeout_record)
    assert attr_timeout is not None
    assert attr_timeout.error_category == "timeout_or_budget"

    invariant_record = RunRecord(
        "mock",
        "c-inv",
        1,
        False,
        12,
        "m",
        "r",
        error_class="failed",
        details={"failed_fields": ["coach_messages"]},
    )
    attr_inv = attribute_first_error(invariant_record)
    assert attr_inv is not None
    assert attr_inv.error_category == "invariant_mismatch"


def test_report_includes_reliability_and_first_errors_while_staying_backward_compatible():
    # Single-repeat all-passing batch must leave reliability=None & first_errors=()
    single_ok = build_report([
        RunRecord("mock", "a", 1, True, 10, "m", "r"),
    ])
    assert single_ok.reliability is None
    assert single_ok.first_errors == ()
    assert "Pass@k" not in render_markdown(single_ok)

    # Multi-repeat batch with failures populates both reliability and first_errors cleanly
    multi = build_report([
        RunRecord("mock", "case-1", 1, True, 10, "m", "r", repeat_index=0),
        RunRecord("mock", "case-1", 1, False, 10, "m", "r", repeat_index=1, error_class="failed", details={"failed_fields": ["plan_activations"]}),
    ])
    assert multi.reliability is not None
    assert multi.reliability["k"] == 2
    assert multi.reliability["pass_at_k"] == 1.0
    assert multi.reliability["pass_pow_k"] == 0.0
    assert len(multi.first_errors) == 1
    assert multi.first_errors[0]["error_category"] == "invariant_mismatch"
    md = render_markdown(multi)
    assert "Pass^k：0.0" in md
    payload = json.loads(render_json(multi))
    assert payload["reliability"]["pass_pow_k"] == 0.0
    assert len(payload["first_errors"]) == 1


def test_observe_database_reads_bounded_run_events(tmp_path, monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE agent_runs (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE agent_run_events (
            run_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            step TEXT,
            attempt INTEGER,
            occurred_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        INSERT INTO agent_runs VALUES ('run-1', 'u-1', 'failed', '2026-11-27T00:00:00Z');
        INSERT INTO agent_run_events VALUES (
            'run-1', 1, 'TOOL_FINISHED', 'tool_meals', 1, '2026-11-27T00:00:01Z',
            '{"outcome": "failed", "error_code": "MODEL_TIMEOUT", "error_type": "timeout"}'
        );
        """
    )
    user_root = tmp_path / "users" / "u-1"
    (user_root / "plans").mkdir(parents=True)
    (user_root / "plan-drafts").mkdir(parents=True)

    class _ConnProxy:
        def execute(self, sql: str, params=()):
            if "information_schema.tables" in sql:
                return conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            return conn.execute(sql, params)

    class _FakeDb:
        def __init__(self, *_a, **_kw) -> None:
            pass

        @contextmanager
        def connection(self):
            yield _ConnProxy()

    monkeypatch.setattr("backend.task_evaluation.observation.PostgresDatabase", _FakeDb)
    try:
        facts = observe_database(
            _FakeDb(),
            actors={"primary": "u-1"},
            data_dir=tmp_path,
        )
        assert "run_events" in facts
        assert len(facts["run_events"]) == 1
        assert facts["run_events"][0]["event_type"] == "TOOL_FINISHED"
        assert facts["run_events"][0]["error_code"] == "MODEL_TIMEOUT"
    finally:
        conn.close()
