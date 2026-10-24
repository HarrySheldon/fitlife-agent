"""CLI tests: mock is the safe default, live needs explicit admission."""
from __future__ import annotations

import pytest

from backend.task_evaluation.cli import parse_args


def test_mode_defaults_to_mock():
    args = parse_args(["--suite", "suite.json"])
    assert args.mode == "mock"
    assert args.allow_live is False


def test_live_without_allow_live_is_rejected():
    with pytest.raises(SystemExit):
        parse_args(["--mode", "live", "--suite", "s.json"])


def test_live_with_allow_live_and_positive_budgets_is_accepted():
    args = parse_args([
        "--mode", "live", "--allow-live", "--suite", "s.json",
        "--max-calls", "10", "--max-tokens", "1000", "--max-seconds", "60",
    ])
    assert args.mode == "live"
    assert args.allow_live is True


@pytest.mark.parametrize("flags", [
    ["--mode", "live", "--allow-live", "--suite", "s.json", "--max-calls", "0"],
    ["--mode", "live", "--allow-live", "--suite", "s.json", "--max-tokens", "0"],
    ["--mode", "live", "--allow-live", "--suite", "s.json", "--max-seconds", "0"],
])
def test_live_with_a_zero_budget_is_rejected(flags):
    with pytest.raises(SystemExit):
        parse_args(flags)


def test_live_is_rejected_before_any_provider_is_built(monkeypatch):
    """The admission check must run first; a live run is never constructed unpaid."""
    constructed = []

    import backend.task_evaluation.cli as cli

    monkeypatch.setattr(cli, "_build_provider", lambda mode: constructed.append(mode))
    with pytest.raises(SystemExit):
        cli.main(["--mode", "live", "--suite", "s.json"])
    assert constructed == []


def test_mock_run_writes_json_and_markdown_reports(tmp_path):
    """A default mock run executes the suite and leaves both report artifacts."""
    import json

    import backend.task_evaluation.cli as cli

    suite = {
        "schema_version": 1,
        "scenarios": [{"id": "empty", "version": 1, "expected": {"confirmed_meals": 0}}],
    }
    suite_path = tmp_path / "suite.json"
    suite_path.write_text(json.dumps(suite), encoding="utf-8")
    output = tmp_path / "out"

    code = cli.main(["--mode", "mock", "--suite", str(suite_path), "--output", str(output)])

    assert code == 0
    assert (output / "report.json").exists()
    assert (output / "report.md").exists()
    payload = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert payload["groups"]["mock"]["successes"] == 1


def test_live_run_is_not_executed_in_this_stage(tmp_path, capsys):
    """Live admission passes, but execution is intentionally not wired yet."""
    import json

    import backend.task_evaluation.cli as cli

    suite_path = tmp_path / "suite.json"
    suite_path.write_text(json.dumps({"schema_version": 1, "scenarios": []}), encoding="utf-8")

    code = cli.main([
        "--mode", "live", "--allow-live", "--suite", str(suite_path),
        "--max-calls", "1", "--max-tokens", "1", "--max-seconds", "1",
        "--output", str(tmp_path / "out"),
    ])
    assert code == 2


@pytest.mark.parametrize("status", ["failed", "unsupported", "budget_exceeded", "deadline_exceeded"])
def test_nonpassing_suite_returns_one_and_writes_partial_reports(tmp_path, monkeypatch, status):
    import json
    import backend.task_evaluation.cli as cli
    import backend.task_evaluation.runner as runner
    from backend.task_evaluation.report import RunRecord
    suite_path = tmp_path / "suite.json"
    suite_path.write_text(json.dumps({"schema_version": 1, "scenarios": [{"id": "case", "version": 1}]}), encoding="utf-8")
    monkeypatch.setattr(runner, "run_suite", lambda *args, **kwargs: [RunRecord("mock", "case", 1, False, None, None, None, error_class=status)])
    output = tmp_path / "artifacts"
    assert cli.main(["--suite", str(suite_path), "--output", str(output)]) == 1
    assert (output / "report.json").exists()


def test_invalid_suite_is_rejected_before_provider_or_artifacts(tmp_path, monkeypatch):
    import backend.task_evaluation.cli as cli
    suite_path = tmp_path / "suite.json"
    suite_path.write_text('{"secret":"sensitive"}', encoding="utf-8")
    calls = []
    monkeypatch.setattr(cli, "_build_provider", lambda mode: calls.append(mode))
    assert cli.main(["--suite", str(suite_path), "--output", str(tmp_path / "out")]) == 2
    assert calls == []
    assert not (tmp_path / "out").exists()


def test_strategy_repeat_and_cache_state_default_to_the_reference_side():
    args = parse_args(["--suite", "s.json"])
    assert args.strategy == "reference"
    assert args.repeat == 1
    assert args.cache_state == "cold"
    assert args.compare is None


def test_repeat_must_be_positive():
    with pytest.raises(SystemExit):
        parse_args(["--suite", "s.json", "--repeat", "0"])


def test_unknown_strategy_or_cache_state_is_rejected():
    with pytest.raises(SystemExit):
        parse_args(["--suite", "s.json", "--strategy", "turbo"])
    with pytest.raises(SystemExit):
        parse_args(["--suite", "s.json", "--cache-state", "lukewarm"])


def test_compare_does_not_require_a_suite_and_refuses_one():
    args = parse_args(["--compare", "ref", "opt"])
    assert args.compare == ("ref", "opt")
    assert args.suite is None
    with pytest.raises(SystemExit):
        parse_args(["--compare", "ref", "opt", "--suite", "s.json"])


def test_compare_never_builds_a_provider(tmp_path, monkeypatch):
    import json

    import backend.task_evaluation.cli as cli

    built = []
    monkeypatch.setattr(cli, "_build_provider", lambda mode: built.append(mode))
    for name in ("ref", "opt"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "report.json").write_text(json.dumps({"records": []}), encoding="utf-8")

    code = cli.main(["--compare", str(tmp_path / "ref"), str(tmp_path / "opt"),
                     "--output", str(tmp_path / "out")])

    assert built == []
    assert code == 1  # no matched pair is not a successful comparison


def test_compare_writes_matched_pairs_and_a_quality_gate(tmp_path, monkeypatch):
    import json

    import backend.task_evaluation.cli as cli

    def record(strategy, ms):
        return {
            "mode": "mock", "case_id": "perf-zh", "version": 1, "success": True,
            "total_tokens": 100, "model": "synthetic", "rule_version": "fitlife-safety-v1",
            "processing_ms": ms, "strategy": strategy, "cache_state": "cold",
            "repeat_index": 0, "invariant_fingerprint": "a" * 64,
        }

    for name, payload in (("ref", [record("reference", 100.0)]),
                          ("opt", [record("optimized", 80.0)])):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "report.json").write_text(json.dumps({"records": payload}), encoding="utf-8")

    output = tmp_path / "out"
    code = cli.main(["--compare", str(tmp_path / "ref"), str(tmp_path / "opt"),
                     "--output", str(output)])

    assert code == 0
    payload = json.loads((output / "comparison.json").read_text(encoding="utf-8"))
    assert payload["summary"]["matched_count"] == 1
    assert payload["summary"]["latency_reduction_percent"] == 20.0
    assert payload["quality_gate"] == {"every_case_paired": True,
                                       "no_rejected_pairs": True,
                                       "has_successful_pair": True}
    assert (output / "comparison.md").exists()
