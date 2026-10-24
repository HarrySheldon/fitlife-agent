"""Pair two strategies on the same cases and refuse to invent a number.

Pairing is keyed on the case, its version and the repeat index. Everything else
that could make the two sides incomparable -- run mode, cache state, invariant
fingerprint -- is checked *after* the match, so a mismatch is reported with a
reason instead of silently shrinking the sample.

A reduction percentage is only produced from a positive baseline of successful
pairs. Failures still count toward cost; they never enter the latency
distribution, because a fast failure is not a fast answer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from backend.task_evaluation.report import RunRecord


def reduction_percent(baseline: float | None, optimized: float | None) -> float | None:
    """Percentage saved relative to the baseline; negative means a regression."""
    if baseline is None or optimized is None:
        return None
    if baseline <= 0:
        return None
    return (baseline - optimized) / baseline * 100


@dataclass(frozen=True)
class PairingRejection:
    case_id: str
    reason: str


@dataclass(frozen=True)
class PairedResult:
    matched: tuple[tuple[RunRecord, RunRecord], ...] = ()
    rejected: tuple[PairingRejection, ...] = ()
    unmatched: tuple[RunRecord, ...] = ()


@dataclass(frozen=True)
class PairedSummary:
    matched_count: int
    success_pairs: int
    failure_pairs: int
    unmatched_count: int
    rejected: tuple[PairingRejection, ...] = ()
    latency_reduction_percent: float | None = None
    token_reduction_percent: float | None = None
    reference_tokens: int | None = None
    optimized_tokens: int | None = None
    details: dict = field(default_factory=dict)


def _key(record: RunRecord) -> tuple[str, int, int]:
    return (record.case_id, record.version, record.repeat_index)


def _index(records: Iterable[RunRecord], duplicate_reason: str):
    index: dict[tuple[str, int, int], RunRecord] = {}
    duplicates: list[PairingRejection] = []
    for record in records:
        key = _key(record)
        if key in index:
            # Two runs claiming the same slot make the pairing ambiguous; drop
            # both rather than picking whichever arrived last.
            duplicates.append(PairingRejection(record.case_id, duplicate_reason))
            index.pop(key, None)
            continue
        index[key] = record
    return index, duplicates


def pair_records(reference: Sequence[RunRecord],
                 optimized: Sequence[RunRecord]) -> PairedResult:
    reference_index, reference_duplicates = _index(reference, "duplicate_reference")
    optimized_index, optimized_duplicates = _index(optimized, "duplicate_optimized")
    rejected: list[PairingRejection] = [*reference_duplicates, *optimized_duplicates]
    matched: list[tuple[RunRecord, RunRecord]] = []
    unmatched: list[RunRecord] = []

    for key in sorted(set(reference_index) | set(optimized_index)):
        left = reference_index.get(key)
        right = optimized_index.get(key)
        if left is None or right is None:
            unmatched.append(left if right is None else right)
            continue
        if left.mode != right.mode:
            rejected.append(PairingRejection(left.case_id, "mode_mismatch"))
        elif left.cache_state != right.cache_state:
            rejected.append(PairingRejection(left.case_id, "cache_state_mismatch"))
        elif left.invariant_fingerprint != right.invariant_fingerprint:
            rejected.append(PairingRejection(left.case_id, "invariant_mismatch"))
        else:
            matched.append((left, right))

    return PairedResult(matched=tuple(matched), rejected=tuple(rejected),
                        unmatched=tuple(unmatched))


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def paired_summary(result: PairedResult) -> PairedSummary:
    success_pairs = [(left, right) for left, right in result.matched
                     if left.success and right.success]
    reference_ms = [left.processing_ms for left, _ in success_pairs
                    if left.processing_ms is not None]
    optimized_ms = [right.processing_ms for _, right in success_pairs
                    if right.processing_ms is not None]
    latency = (reduction_percent(_mean(reference_ms), _mean(optimized_ms))
               if reference_ms and optimized_ms else None)

    reference_tokens = None
    optimized_tokens = None
    if success_pairs and all(left.total_tokens is not None and right.total_tokens is not None
                             for left, right in success_pairs):
        reference_tokens = sum(left.total_tokens for left, _ in success_pairs)
        optimized_tokens = sum(right.total_tokens for _, right in success_pairs)

    return PairedSummary(
        matched_count=len(result.matched),
        success_pairs=len(success_pairs),
        failure_pairs=len(result.matched) - len(success_pairs),
        unmatched_count=len(result.unmatched),
        rejected=result.rejected,
        latency_reduction_percent=latency,
        token_reduction_percent=reduction_percent(reference_tokens, optimized_tokens),
        reference_tokens=reference_tokens,
        optimized_tokens=optimized_tokens,
    )


def render_comparison(result: PairedResult, summary: PairedSummary) -> str:
    """Markdown for the paired run. Withheld numbers are printed as null."""
    def value(number):
        return "null" if number is None else f"{number:.2f}"

    lines = [
        "# 策略配对对照",
        "",
        f"- 配对成功：{summary.matched_count}",
        f"- 双方均成功：{summary.success_pairs}",
        f"- 含失败：{summary.failure_pairs}",
        f"- 单侧缺失：{summary.unmatched_count}",
        f"- 拒配：{len(summary.rejected)}",
        "",
        "## 结果",
        "",
        f"- 延迟下降：{value(summary.latency_reduction_percent)}%（仅成功配对；负数为退化）",
        f"- token 下降：{value(summary.token_reduction_percent)}%（任一侧未知即 null）",
        f"- 已知 token：reference={summary.reference_tokens}，optimized={summary.optimized_tokens}",
        "",
    ]
    if summary.rejected:
        lines.append("## 拒配原因")
        lines.append("")
        for rejection in summary.rejected:
            lines.append(f"- {rejection.case_id}: {rejection.reason}")
        lines.append("")
    if result.unmatched:
        lines.append("## 单侧缺失用例")
        lines.append("")
        for record in result.unmatched:
            lines.append(f"- {record.case_id} (strategy={record.strategy}, repeat={record.repeat_index})")
        lines.append("")
    lines.extend([
        "## 说明",
        "",
        "- mock 运行只能证明配对流程与计数，不代表真实模型提速。",
        "- 冷 reference 不与热 optimized 配对；Provider 缓存不能由 cold 标志声称清空。",
        "",
    ])
    return "\n".join(lines)
