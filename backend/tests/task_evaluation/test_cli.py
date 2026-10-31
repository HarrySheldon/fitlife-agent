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
    assert payload["summary"]["paired_count"] == 1
    assert payload["summary"]["latency_reduction_percent"] == 20.0
    assert payload["summary"]["reference_cost_per_success"] == 100.0
    assert payload["summary"]["coverage"]["runs"] == 2
    assert payload["quality_gate"] == {
        "passed": True, "reasons": [], "violations": {
            "unauthorized_access": 0, "duplicate_writes": 0, "invalid_activations": 0},
        "regressions": [], "matched_count": 1, "success_pairs": 1,
        "unmatched_count": 0, "rejected_count": 0}
    assert (output / "comparison.md").exists()


def _manifest(directory, suite):
    import json

    (directory / "manifest.json").write_text(json.dumps({"suite": suite}), encoding="utf-8")


def test_two_different_suites_are_never_averaged(tmp_path):
    """One comparison covers one suite; a coach/plan mix is not a speed."""
    import json

    import backend.task_evaluation.cli as cli

    record = {
        "mode": "mock", "case_id": "perf-zh", "version": 1, "success": True,
        "total_tokens": 100, "model": "synthetic", "rule_version": "fitlife-safety-v1",
        "processing_ms": 100.0, "strategy": "reference", "cache_state": "cold",
        "repeat_index": 0, "invariant_fingerprint": "a" * 64,
    }
    for name, suite in (("ref", "scenarios/performance_coach.json"),
                        ("opt", "scenarios/performance_plans.json")):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "report.json").write_text(json.dumps({"records": [record]}), encoding="utf-8")
        _manifest(directory, suite)

    code = cli.main(["--compare", str(tmp_path / "ref"), str(tmp_path / "opt"),
                     "--output", str(tmp_path / "out")])

    assert code == 2
    assert not (tmp_path / "out" / "comparison.json").exists()


def test_a_run_records_which_suite_it_came_from(tmp_path):
    """Without the manifest a later comparison cannot refuse a mixed pair."""
    import json

    import backend.task_evaluation.cli as cli

    suite = tmp_path / "suite.json"
    suite.write_text(json.dumps({"schema_version": 1, "scenarios": []}), encoding="utf-8")
    output = tmp_path / "run"

    code = cli.main(["--suite", str(suite), "--output", str(output)])

    assert code == 0
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["suite"] == str(suite)
    assert manifest["strategy"] == "reference"
    assert manifest["cache_state"] == "cold"


# --------------------------------------------------------------------------
# offline admission dry-run
# --------------------------------------------------------------------------

def _write_admission_inputs(tmp_path, *, authorized=True, actual_overrides=None):
    """A minimal admissible batch, written as JSON so the CLI reads real files."""
    import json

    from backend.task_evaluation.acceptance import EvaluationBudget

    digest = "a" * 64
    sha = "b" * 40
    budget = EvaluationBudget(max_calls=10, max_tokens=1000, max_seconds=30).model_dump()
    manifest = {
        "code_sha": sha, "diff_digest": digest, "suite_digest": digest,
        "connection_ref": "approved-1", "connection_fingerprint": digest,
        "provider": "openai", "model": "test-model", "protocol": "responses",
        "engine": "unified_coach", "strategy": "reference", "phase": "compare",
        "invariant_fingerprint": digest, "treatment_fingerprint": digest,
        "review_mode": "off", "grounding_mode": "legacy", "synthetic_only": True,
        "repeat": 1, "annotation_protocol_version": "annotation-v1", "budget": budget,
    }
    actual = {
        "code_sha": sha, "diff_digest": digest, "suite_digest": digest,
        "connection_fingerprint": digest, "provider": "openai", "model": "test-model",
        "protocol": "responses", "engine": "unified_coach", "review_mode": "off",
        "grounding_mode": "legacy", "invariant_fingerprint": digest,
        "treatment_fingerprint": digest, "scenario_count": 5,
        "has_real_user_data": False,
        "provider_registry": ["openai", "custom"],
        "protocol_registry": ["responses", "chat_completions"],
        "engine_registry": ["unified_coach"],
        "safety_mode_registry": ["off", "shadow", "enforce", "legacy", "evidence"],
        "max_cases": 100,
    }
    actual.update(actual_overrides or {})
    manifest_path = tmp_path / "manifest.json"
    actual_path = tmp_path / "actual.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    actual_path.write_text(json.dumps(actual), encoding="utf-8")
    args = ["--admit-manifest", str(manifest_path), "--admit-actual", str(actual_path)]
    if authorized:
        authorization_path = tmp_path / "authorization.json"
        authorization_path.write_text(json.dumps({
            "approved_by": "operator", "expires_at": 2_000_000_000.0, "reference": "batch-1",
        }), encoding="utf-8")
        args += ["--admit-authorization", str(authorization_path)]
    return args


def test_admit_dry_run_admits_a_matching_batch(tmp_path, capsys):
    import backend.task_evaluation.cli as cli

    assert cli.main(_write_admission_inputs(tmp_path)) == 0
    assert "ADMITTED" in capsys.readouterr().out


def test_admit_dry_run_rejects_without_authorization(tmp_path, capsys):
    import backend.task_evaluation.cli as cli

    assert cli.main(_write_admission_inputs(tmp_path, authorized=False)) == 2
    assert "LIVE_NOT_AUTHORIZED" in capsys.readouterr().out


def test_admit_dry_run_reports_a_mismatch(tmp_path, capsys):
    import backend.task_evaluation.cli as cli

    assert cli.main(_write_admission_inputs(tmp_path, actual_overrides={"model": "other"})) == 2
    assert "MISMATCH_MODEL" in capsys.readouterr().out


def test_admit_dry_run_never_constructs_a_provider(tmp_path, monkeypatch):
    """A dry-run validates; it must not reach the provider factory."""
    constructed = []

    import backend.task_evaluation.cli as cli

    monkeypatch.setattr(cli, "_build_provider", lambda mode: constructed.append(mode))
    cli.main(_write_admission_inputs(tmp_path))

    assert constructed == []


def test_admit_and_suite_cannot_be_combined():
    with pytest.raises(SystemExit):
        parse_args(["--admit-manifest", "m.json", "--admit-actual", "a.json", "--suite", "s.json"])


def test_admit_manifest_requires_actual():
    with pytest.raises(SystemExit):
        parse_args(["--admit-manifest", "m.json"])


def test_admit_dry_run_tolerates_a_utf8_bom(tmp_path, capsys):
    """PowerShell on Windows writes a BOM by default; that must not read as invalid."""
    import backend.task_evaluation.cli as cli

    args = _write_admission_inputs(tmp_path)
    for path in (args[1], args[3], args[5]):
        raw = (tmp_path / path.split("\\")[-1]).read_bytes()
        if not raw.startswith(b"\xef\xbb\xbf"):
            (tmp_path / path.split("\\")[-1]).write_bytes(b"\xef\xbb\xbf" + raw)

    assert cli.main(args) == 0
    assert "ADMITTED" in capsys.readouterr().out
