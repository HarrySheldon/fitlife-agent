"""Metrics and reports for business-task evaluation runs.

The invariants here are about honesty rather than arithmetic: failures are not dropped
to improve a rate, a missing measurement is `unknown` and never zero, and mock results
are never merged with live results into a single figure.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class RunRecord:
    mode: str
    case_id: str
    version: int
    success: bool
    total_tokens: int | None
    model: str | None
    rule_version: str | None
    git_sha: str | None = None
    workspace_diff: str | None = None
    config_fingerprint: str | None = None
    prompt_version: str | None = None
    processing_ms: float | None = None
    candidate_ms: float | None = None
    calls: int | None = None
    retries: int | None = None
    error_class: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def cost_per_success(total_tokens: int, successes: int) -> float | None:
    return total_tokens / successes if successes else None


@dataclass(frozen=True)
class GroupSummary:
    mode: str
    total: int
    successes: int
    failures: int
    total_tokens: int | None
    cost_per_success: float | None
    failure_processing_ms: tuple[float, ...] = field(default=())
    known_total_tokens: int = 0
    unknown_token_count: int = 0
    coverage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Report:
    total_runs: int
    total_successes: int
    total_tokens: int | None
    cost_per_success: float | None
    model_version: str
    rule_version: str
    groups: dict[str, GroupSummary]
    records: tuple[RunRecord, ...]


def _sum_tokens(records: list[RunRecord]) -> int | None:
    if any(record.total_tokens is None for record in records):
        return None
    return sum(record.total_tokens for record in records if record.total_tokens is not None)


def _group(records: list[RunRecord], mode: str) -> GroupSummary:
    group_records = [r for r in records if r.mode == mode]
    successes = sum(1 for r in group_records if r.success)
    tokens = _sum_tokens(group_records)
    return GroupSummary(
        mode=mode,
        total=len(group_records),
        successes=successes,
        failures=len(group_records) - successes,
        total_tokens=tokens,
        cost_per_success=cost_per_success(tokens, successes) if tokens is not None else None,
        failure_processing_ms=tuple(
            r.processing_ms for r in group_records if not r.success and r.processing_ms is not None
        ),
        known_total_tokens=sum(r.total_tokens if r.total_tokens is not None else r.details.get("known_estimated_tokens") or 0 for r in group_records),
        unknown_token_count=sum(r.total_tokens is None for r in group_records),
        coverage={status: sum(("passed" if r.success else r.error_class or "failed") == status for r in group_records)
                  for status in sorted({"passed" if r.success else r.error_class or "failed" for r in group_records})},
    )


def build_report(records: list[RunRecord]) -> Report:
    successes = sum(1 for r in records if r.success)
    tokens = _sum_tokens(records) if len({r.mode for r in records}) <= 1 else None
    modes = {r.mode for r in records}
    models = {r.model for r in records}
    rules = {r.rule_version for r in records}
    # A single model/rule version is only meaningful when every record belongs to one
    # mode; mixing mock and live must not produce a summary that reads as one result.
    single_mode = len(modes) <= 1
    return Report(
        total_runs=len(records),
        total_successes=successes,
        total_tokens=tokens,
        cost_per_success=cost_per_success(tokens, successes) if tokens is not None else None,
        model_version=next(iter(models)) if single_mode and len(models) == 1 and None not in models else "unknown",
        rule_version=next(iter(rules)) if single_mode and len(rules) == 1 and None not in rules else "unknown",
        groups={mode: _group(records, mode) for mode in sorted(modes)},
        records=tuple(records),
    )


def render_markdown(report: Report) -> str:
    lines = [
        "# 任务评估报告",
        "",
        f"- 总运行：{report.total_runs}",
        f"- 成功：{report.total_successes}",
        f"- 模型版本：{report.model_version}",
        f"- 规则版本：{report.rule_version}",
        "",
    ]
    for mode, group in report.groups.items():
        lines.append(f"## {mode}")
        lines.append("")
        lines.append(f"- 成功：{group.successes}")
        lines.append(f"- 失败：{group.failures}")
        lines.append(f"- 已知 tokens 小计：{group.known_total_tokens}；未知数量：{group.unknown_token_count}")
        lines.append(f"- 覆盖状态：{json.dumps(group.coverage, ensure_ascii=False)}")
        if mode == "mock":
            lines.append("- tokens 为字符估算；非 Provider 使用量或付费成本。")
        lines.append(
            f"- 每成功任务成本：{group.cost_per_success if group.cost_per_success is not None else 'null'}"
        )
        # Failure timing is reported separately and never turned into a percentile
        # claim when the sample cannot support one.
        if group.failure_processing_ms:
            lines.append(f"- 失败耗时（ms）：{', '.join(str(int(v)) for v in group.failure_processing_ms)}")
        lines.append("")
    lines.extend(["## 运行详情", "", "```json", json.dumps([asdict(r) for r in report.records], ensure_ascii=False, indent=2, allow_nan=False), "```", ""])
    return "\n".join(lines)


def render_json(report: Report) -> str:
    """Machine-readable report. Carries provenance only, never credentials or raw input."""
    payload = {
        "total_runs": report.total_runs,
        "total_successes": report.total_successes,
        "total_tokens": report.total_tokens,
        "cost_per_success": report.cost_per_success,
        "model_version": report.model_version,
        "rule_version": report.rule_version,
        "groups": {mode: asdict(group) for mode, group in report.groups.items()},
        "records": [asdict(record) for record in report.records],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
