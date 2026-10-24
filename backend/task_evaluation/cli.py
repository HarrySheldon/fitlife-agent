"""Command-line entry point for the business-task evaluation runner.

The default is mock. Live runs require ``--allow-live`` and three positive budgets, and
that admission check happens before any provider object is constructed, so a live run
is never built and then asked whether it was allowed.

``--compare`` is read-only: it reads two finished report directories, pairs the runs
and never constructs a provider or a suite.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Mock runs still carry a finite budget so an accidental infinite loop cannot run
# forever; these are local limits, not provider spend.
DEFAULT_MOCK_CALLS = 200
DEFAULT_MOCK_SECONDS = 300
DEFAULT_MOCK_TOKENS = 200000


@dataclass(frozen=True)
class CliArgs:
    mode: str
    suite: str | None
    output: str
    max_calls: int
    max_tokens: int
    max_seconds: int
    allow_live: bool
    strategy: str = "reference"
    repeat: int = 1
    cache_state: str = "cold"
    compare: tuple[str, str] | None = None


def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def parse_args(argv: list[str]) -> CliArgs:
    parser = argparse.ArgumentParser(prog="task-evaluation")
    parser.add_argument("--mode", choices=("mock", "live"), default="mock")
    parser.add_argument("--suite")
    parser.add_argument("--output", default=".tmp/task-evaluation")
    parser.add_argument("--max-calls", type=_positive_int)
    parser.add_argument("--max-tokens", type=_positive_int)
    parser.add_argument("--max-seconds", type=_positive_int)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--strategy", choices=("reference", "optimized"), default="reference")
    parser.add_argument("--repeat", type=_positive_int, default=1)
    parser.add_argument("--cache-state", choices=("cold", "warm"), default="cold")
    parser.add_argument("--compare", nargs=2, metavar=("REFERENCE", "OPTIMIZED"))
    raw = parser.parse_args(argv)

    if raw.compare:
        if raw.suite:
            parser.error("--compare reads finished reports and does not accept --suite")
        if raw.mode != "mock":
            parser.error("--compare is read-only and does not run a provider")
    elif not raw.suite:
        parser.error("--suite is required unless --compare is used")

    if raw.mode == "live":
        if not raw.allow_live:
            parser.error("live mode requires --allow-live")
        missing = [
            name for name, value in (
                ("--max-calls", raw.max_calls),
                ("--max-tokens", raw.max_tokens),
                ("--max-seconds", raw.max_seconds),
            ) if value is None
        ]
        if missing:
            parser.error("live mode requires " + ", ".join(missing))

    return CliArgs(
        mode=raw.mode,
        suite=raw.suite,
        output=raw.output,
        max_calls=raw.max_calls or 0,
        max_tokens=raw.max_tokens or 0,
        max_seconds=raw.max_seconds or 0,
        allow_live=raw.allow_live,
        strategy=raw.strategy,
        repeat=raw.repeat,
        cache_state=raw.cache_state,
        compare=tuple(raw.compare) if raw.compare else None,
    )


def _build_provider(mode: str):
    if mode == "live":
        raise RuntimeError("A live provider must not be constructed before admission")
    from backend.task_evaluation.runner import ScriptedGateway

    return ScriptedGateway()


def _git_sha() -> str | None:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5
        )
    except Exception:
        return None
    return result.stdout.strip() or None


def _load_records(directory: str):
    from backend.task_evaluation.report import RunRecord

    payload = json.loads((Path(directory) / "report.json").read_text(encoding="utf-8"))
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("report has no records")
    return [RunRecord(**record) for record in records]


def _compare(args: CliArgs) -> int:
    from backend.task_evaluation.comparison import (
        pair_records,
        paired_summary,
        render_comparison,
    )

    try:
        reference = _load_records(args.compare[0])
        optimized = _load_records(args.compare[1])
    except Exception:
        print("invalid comparison input", file=sys.stderr)
        return 2

    result = pair_records(reference, optimized)
    summary = paired_summary(result)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "comparison.md").write_text(render_comparison(result, summary), encoding="utf-8")
    (output / "comparison.json").write_text(json.dumps({
        "matched": [[left.case_id, right.case_id] for left, right in result.matched],
        "rejected": [{"case_id": item.case_id, "reason": item.reason} for item in result.rejected],
        "unmatched": [record.case_id for record in result.unmatched],
        "summary": {
            "matched_count": summary.matched_count,
            "success_pairs": summary.success_pairs,
            "failure_pairs": summary.failure_pairs,
            "unmatched_count": summary.unmatched_count,
            "latency_reduction_percent": summary.latency_reduction_percent,
            "token_reduction_percent": summary.token_reduction_percent,
            "reference_tokens": summary.reference_tokens,
            "optimized_tokens": summary.optimized_tokens,
        },
        "quality_gate": {
            "every_case_paired": not result.unmatched,
            "no_rejected_pairs": not result.rejected,
            "has_successful_pair": summary.success_pairs > 0,
        },
    }, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    complete = (summary.matched_count > 0 and not result.rejected and not result.unmatched)
    return 0 if complete else 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if args.compare:
        return _compare(args)
    if args.mode == "live":
        # Admission is complete, but a live provider is deliberately not constructed:
        # S0 has no approved provider, so live execution is not wired yet.
        print("live execution is not enabled in this stage", file=sys.stderr)
        return 2
    # Only now, after admission, may a provider exist; in mock mode it is a scripted
    # gateway that refuses the network.

    from backend.task_evaluation.budget import BatchBudget
    from backend.task_evaluation.contracts import Suite
    from backend.task_evaluation.report import build_report, render_json, render_markdown
    from backend.task_evaluation.runner import run_suite
    from backend.task_evaluation.provenance import fingerprint

    try:
        suite = Suite.model_validate(json.loads(Path(args.suite).read_text(encoding="utf-8")))
    except Exception:
        print("invalid evaluation suite", file=sys.stderr)
        return 2
    _build_provider(args.mode)
    budget = BatchBudget(float(args.max_calls or DEFAULT_MOCK_CALLS), args.max_tokens or DEFAULT_MOCK_TOKENS)
    deadline = time.monotonic() + float(args.max_seconds or DEFAULT_MOCK_SECONDS)
    config_fingerprint = fingerprint({"suite": suite.model_dump(mode="json"), "mode": args.mode,
                                      "calls": budget.limit, "tokens": budget.token_limit,
                                      "seconds": args.max_seconds or DEFAULT_MOCK_SECONDS})
    records = []
    for repeat_index in range(args.repeat):
        records.extend(run_suite(
            suite.scenarios,
            mode=args.mode,
            deadline=deadline,
            budget=budget,
            git_sha=_git_sha(),
            config_fingerprint=config_fingerprint,
            strategy=args.strategy,
            cache_state=args.cache_state,
            repeat_index=repeat_index,
        ))
    report = build_report(records)

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(render_json(report), encoding="utf-8")
    (output / "report.md").write_text(render_markdown(report), encoding="utf-8")

    complete = all(record.success for record in records)
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
