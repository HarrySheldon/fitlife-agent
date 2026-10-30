"""Pair two strategies on the same cases and refuse to invent a number.

Pairing is keyed on the case, its version and the repeat index. Everything else
that could make the two sides incomparable -- run mode, cache state, invariant
fingerprint -- is checked *after* the match, so a mismatch is reported with a
reason instead of silently shrinking the sample.

A reduction percentage is only produced from a positive baseline of successful
pairs. Failures still count toward cost; they never enter the latency
distribution, because a fast failure is not a fast answer.

D1 adds the part that makes a reduction claim admissible at all: a declared
percentile method, an interval that says "insufficient sample" instead of
inventing one, a cost per success that pays for the failures, and a quality gate
that refuses a faster run which violated a declared safety fact, regressed a case
that used to pass, or changed the engine under test.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from backend.task_evaluation.report import RunRecord

#: Nearest-rank: the returned value is always one that was observed. Interpolation
#: would produce a latency no run ever had, which is not reproducible from the log.
PERCENTILE_METHOD = "nearest-rank"

#: Below this many successful pairs the bootstrap is not reported. The number is
#: a floor for honesty, not a claim of statistical sufficiency.
MINIMUM_INTERVAL_SAMPLE = 8

#: Closed set. A new reason means a new rule, and a report that invents one cannot
#: be compared with the previous run.
GATE_REASONS = frozenset({
    "safety_violation",
    "quality_regression",
    "unmatched_case",
    "rejected_pair",
    "no_comparable_pair",
    "no_successful_pair",
})

#: Which declared fact proves which safety property did not happen. Each fact
#: belongs to exactly one category, so a single failure is never counted twice.
SAFETY_CATEGORIES = ("unauthorized_access", "duplicate_writes", "invalid_activations")
SAFETY_CATEGORY_OF: dict[str, str] = {
    "coach_unapproved_answers": "unauthorized_access",
    "coach_boundary_replies": "unauthorized_access",
    "denials": "unauthorized_access",
    "plan_authorize_denials": "unauthorized_access",
    "confirmed_meals": "duplicate_writes",
    "confirmed_workouts": "duplicate_writes",
    "plan_history": "duplicate_writes",
    "plan_activations": "invalid_activations",
    "plan_head_revision": "invalid_activations",
    "plan_task_states": "invalid_activations",
    "violations": "invalid_activations",
}


def reduction_percent(baseline: float | None, optimized: float | None) -> float | None:
    """Percentage saved relative to the baseline; negative means a regression."""
    if baseline is None or optimized is None:
        return None
    if baseline <= 0:
        return None
    return (baseline - optimized) / baseline * 100


def percentile(values: Sequence[float], fraction: float) -> float | None:
    """Nearest-rank percentile over the values that were actually observed."""
    if not 0 < fraction <= 1:
        raise ValueError("percentile fraction must be in (0, 1]")
    ordered = sorted(value for value in values if value is not None)
    if not ordered:
        return None
    rank = min(len(ordered), max(1, math.ceil(fraction * len(ordered))))
    return ordered[rank - 1]


@dataclass(frozen=True)
class Distribution:
    """Size, range and two percentiles, with the method that produced them."""

    count: int = 0
    minimum: float | None = None
    maximum: float | None = None
    p50: float | None = None
    p95: float | None = None
    method: str = PERCENTILE_METHOD

    def as_record(self) -> dict:
        return {"count": self.count, "minimum": self.minimum, "maximum": self.maximum,
                "p50": self.p50, "p95": self.p95, "method": self.method}


def distribution(values: Iterable[float | None]) -> Distribution:
    """Missing measurements are dropped, never read as zero."""
    observed = [value for value in values if value is not None]
    return Distribution(count=len(observed),
                        minimum=min(observed) if observed else None,
                        maximum=max(observed) if observed else None,
                        p50=percentile(observed, 0.50),
                        p95=percentile(observed, 0.95))


@dataclass(frozen=True)
class Interval:
    """A bootstrap interval, or the reason there is none."""

    low: float | None = None
    high: float | None = None
    resamples: int = 0
    reason: str | None = None

    def as_record(self) -> dict:
        return {"low": self.low, "high": self.high, "resamples": self.resamples,
                "reason": self.reason}


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def bootstrap_median_interval(values: Sequence[float], *, resamples: int = 1000,
                              seed: int = 20260101) -> Interval:
    """Percentile bootstrap of the median, from a fixed seed.

    A small sample is not evidence of a small effect, so below
    ``MINIMUM_INTERVAL_SAMPLE`` the honest answer is "no interval".
    """
    observed = [value for value in values if value is not None]
    if len(observed) < MINIMUM_INTERVAL_SAMPLE:
        return Interval(resamples=0, reason="insufficient_sample")
    generator = random.Random(seed)
    medians = [_median([generator.choice(observed) for _ in observed])
               for _ in range(resamples)]
    return Interval(low=percentile(medians, 0.025), high=percentile(medians, 0.975),
                    resamples=resamples)


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
class MeasurementCoverage:
    """How much of the run was actually measured, reported next to the results.

    Kept apart from the safety counts on purpose: an unknown token count makes a
    cost claim weaker, it does not make the product unsafe.
    """

    runs: int = 0
    unknown_usage: int = 0
    incomplete_attempts: int = 0
    cleanup_failed: int = 0

    @property
    def unknown_usage_rate(self) -> float | None:
        return self.unknown_usage / self.runs if self.runs else None

    def as_record(self) -> dict:
        return {"runs": self.runs, "unknown_usage": self.unknown_usage,
                "unknown_usage_rate": self.unknown_usage_rate,
                "incomplete_attempts": self.incomplete_attempts,
                "cleanup_failed": self.cleanup_failed}


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
    reference_cost_per_success: float | None = None
    optimized_cost_per_success: float | None = None
    #: Bootstrap interval of the per-pair reduction, or the reason there is none.
    #: A point estimate without this is not evidence of anything.
    latency_reduction_interval: Interval = field(default_factory=Interval)
    reference_latency: Distribution = field(default_factory=Distribution)
    optimized_latency: Distribution = field(default_factory=Distribution)
    reference_candidate: Distribution = field(default_factory=Distribution)
    optimized_candidate: Distribution = field(default_factory=Distribution)
    coverage: MeasurementCoverage = field(default_factory=MeasurementCoverage)
    details: dict = field(default_factory=dict)

    @property
    def paired_count(self) -> int:
        return self.matched_count

    @property
    def rejected_pairs(self) -> int:
        return len(self.rejected)


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


def _cost_per_success(records: Sequence[RunRecord]) -> float | None:
    """Tokens of every run divided by the successes.

    Dropping the failures would make a strategy that breaks more tasks look
    cheaper per success, which is the opposite of what the number is for. Any
    unknown token count makes the total unknown rather than smaller.
    """
    successes = sum(1 for record in records if record.success)
    if not successes or not records:
        return None
    if any(record.total_tokens is None for record in records):
        return None
    return sum(record.total_tokens for record in records) / successes


def _coverage(records: Sequence[RunRecord]) -> MeasurementCoverage:
    return MeasurementCoverage(
        runs=len(records),
        unknown_usage=sum(record.total_tokens is None for record in records),
        incomplete_attempts=sum(int(record.details.get("attempts_incomplete") or 0)
                                for record in records),
        cleanup_failed=sum(record.details.get("cleanup_status") == "failed"
                           for record in records),
    )


def bootstrap_mean_ratio_interval(pairs, *, resamples=1000, seed=20260101):
    """Resample whole pairs and recompute the reported ratio of means."""
    if len(pairs) < MINIMUM_INTERVAL_SAMPLE:
        return Interval(reason='insufficient_sample')
    generator = random.Random(seed)
    estimates = []
    for _ in range(resamples):
        sample = [generator.choice(pairs) for _ in pairs]
        value = reduction_percent(_mean([left for left, _ in sample]),
                                  _mean([right for _, right in sample]))
        if value is None:
            return Interval(reason='non_positive_baseline')
        estimates.append(value)
    return Interval(low=percentile(estimates, 0.025), high=percentile(estimates, 0.975),
                    resamples=resamples)


def paired_summary(result: PairedResult) -> PairedSummary:
    """Everything a reader needs to judge the pair, and nothing invented.

    Two denominators on purpose. Latency and token *reductions* use successful
    pairs only, because a fast failure is not a fast answer. Cost per success
    uses every matched run on that side, because dropping the failures makes a
    strategy that breaks more tasks look cheaper.
    """
    success_pairs = [(left, right) for left, right in result.matched
                     if left.success and right.success]
    timed_pairs = [(left.processing_ms, right.processing_ms) for left, right in success_pairs
                   if left.processing_ms is not None and right.processing_ms is not None]
    reference_ms = [left for left, _ in timed_pairs]
    optimized_ms = [right for _, right in timed_pairs]
    latency = (reduction_percent(_mean(reference_ms), _mean(optimized_ms))
               if reference_ms and optimized_ms else None)

    reference_tokens = None
    optimized_tokens = None
    if success_pairs and all(left.total_tokens is not None and right.total_tokens is not None
                             for left, right in success_pairs):
        reference_tokens = sum(left.total_tokens for left, _ in success_pairs)
        optimized_tokens = sum(right.total_tokens for _, right in success_pairs)

    reference_records = [left for left, _ in result.matched]
    optimized_records = [right for _, right in result.matched]
    every_record = [*reference_records, *optimized_records, *result.unmatched]

    # Paired per-case reduction, then a bootstrap of its median. Pairing first is
    # what removes the case-to-case spread from the interval.
    per_pair = [reduction_percent(left.processing_ms, right.processing_ms)
                for left, right in success_pairs
                if left.processing_ms is not None and right.processing_ms is not None]

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
        reference_cost_per_success=_cost_per_success(reference_records),
        optimized_cost_per_success=_cost_per_success(optimized_records),
        latency_reduction_interval=bootstrap_mean_ratio_interval(timed_pairs),
        reference_latency=distribution(left.processing_ms for left, _ in success_pairs),
        optimized_latency=distribution(right.processing_ms for _, right in success_pairs),
        # A candidate time is only recorded once a candidate was verified, so the
        # missing ones are missing by construction rather than by omission.
        reference_candidate=distribution(left.candidate_ms for left, _ in success_pairs),
        optimized_candidate=distribution(right.candidate_ms for _, right in success_pairs),
        coverage=_coverage(every_record),
    )


# -- the quality gate ---------------------------------------------------


@dataclass(frozen=True)
class SafetyViolation:
    """A declared safety fact that did not hold, on either side of the pair."""

    category: str
    case_id: str
    strategy: str | None
    fact: str


def safety_violations(records: Iterable[RunRecord]) -> tuple[SafetyViolation, ...]:
    """Every failed declared safety fact, named by category.

    The facts come from the scenario's own expectations: a case that declares
    ``plan_activations: 0`` and observes one has failed that field, and that
    failure is the violation. Nothing is inferred from timing.
    """
    found: list[SafetyViolation] = []
    for record in records:
        for fact in record.details.get("failed_fields") or ():
            category = SAFETY_CATEGORY_OF.get(fact)
            if category is not None:
                found.append(SafetyViolation(category=category, case_id=record.case_id,
                                             strategy=record.strategy, fact=fact))
    return tuple(found)


@dataclass(frozen=True)
class QualityGate:
    violations: tuple[SafetyViolation, ...] = ()
    regressions: tuple[str, ...] = ()
    unmatched_count: int = 0
    rejected_count: int = 0
    matched_count: int = 0
    success_pairs: int = 0

    @property
    def passed(self) -> bool:
        return not self.reasons

    @property
    def reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.violations:
            reasons.append("safety_violation")
        if self.regressions:
            reasons.append("quality_regression")
        if self.unmatched_count:
            reasons.append("unmatched_case")
        if self.rejected_count:
            reasons.append("rejected_pair")
        if not self.matched_count:
            reasons.append("no_comparable_pair")
        elif not self.success_pairs:
            reasons.append("no_successful_pair")
        return tuple(reasons)

    def counts(self) -> dict[str, int]:
        """Every category is present, so a zero is a measurement and not a gap."""
        counts = {category: 0 for category in SAFETY_CATEGORIES}
        for violation in self.violations:
            counts[violation.category] += 1
        return counts

    def as_record(self) -> dict:
        return {
            "passed": self.passed,
            "reasons": list(self.reasons),
            "violations": self.counts(),
            "regressions": list(self.regressions),
            "matched_count": self.matched_count,
            "success_pairs": self.success_pairs,
            "unmatched_count": self.unmatched_count,
            "rejected_count": self.rejected_count,
        }


def quality_gate(result: PairedResult, summary: PairedSummary) -> QualityGate:
    """Refuse a faster result that is not also the same or better product.

    A case that passed in the reference and fails in the optimized arm is a
    regression even when the failure is unrelated to safety: the two arms are
    supposed to differ in cost, not in outcome.
    """
    every_record = [*[left for left, _ in result.matched],
                    *[right for _, right in result.matched], *result.unmatched]
    regressions = tuple(sorted(left.case_id for left, right in result.matched
                               if left.success and not right.success))
    return QualityGate(
        violations=safety_violations(every_record),
        regressions=regressions,
        unmatched_count=summary.unmatched_count,
        rejected_count=summary.rejected_pairs,
        matched_count=summary.matched_count,
        success_pairs=summary.success_pairs,
    )


def render_comparison(result: PairedResult, summary: PairedSummary,
                      gate: QualityGate | None = None, *,
                      suite: str | None = None) -> str:
    """Markdown for the paired run. Withheld numbers are printed as null."""
    def value(number):
        return "null" if number is None else f"{number:.2f}"

    def _interval_text(interval: Interval) -> str:
        if interval.reason:
            return f"无区间（{interval.reason}，样本不足不代表效应小）"
        return (f"[{value(interval.low)}, {value(interval.high)}]%"
                f"（百分位 bootstrap，{interval.resamples} 次重采样）")

    def spread(item: Distribution):
        if not item.count:
            return "无可比样本"
        return (f"n={item.count}，P50={value(item.p50)}，P95={value(item.p95)}，"
                f"范围 {value(item.minimum)}–{value(item.maximum)}（{item.method}）")

    gate = gate or quality_gate(result, summary)
    lines = [
        "# 策略配对对照",
        "",
        f"- 套件：{suite or '未声明（单套件对照）'}",
        f"- 配对成功：{summary.paired_count}",
        f"- 双方均成功：{summary.success_pairs}",
        f"- 含失败：{summary.failure_pairs}",
        f"- 单侧缺失：{summary.unmatched_count}",
        f"- 拒配：{summary.rejected_pairs}",
        "",
        "## 质量门禁",
        "",
        f"- 通过：{gate.passed}",
        f"- 原因：{', '.join(gate.reasons) if gate.reasons else '无'}",
        f"- 越权实际访问：{gate.counts()['unauthorized_access']}",
        f"- 重复写入：{gate.counts()['duplicate_writes']}",
        f"- 无效激活：{gate.counts()['invalid_activations']}",
        f"- 退化用例：{', '.join(gate.regressions) if gate.regressions else '无'}",
        "",
        "## 结果",
        "",
        f"- 延迟下降：{value(summary.latency_reduction_percent)}%（仅成功配对；负数为退化）",
        f"- 延迟下降区间：{_interval_text(summary.latency_reduction_interval)}",
        f"- token 下降：{value(summary.token_reduction_percent)}%（仅成功配对；任一侧未知即 null）",
        f"- 已知 token：reference={summary.reference_tokens}，optimized={summary.optimized_tokens}",
        f"- 每成功任务成本（含失败）：reference={value(summary.reference_cost_per_success)}，"
        f"optimized={value(summary.optimized_cost_per_success)}",
        "",
        "## 分布",
        "",
        f"- reference 延迟 ms：{spread(summary.reference_latency)}",
        f"- optimized 延迟 ms：{spread(summary.optimized_latency)}",
        f"- reference 候选 ms：{spread(summary.reference_candidate)}",
        f"- optimized 候选 ms：{spread(summary.optimized_candidate)}",
        "",
        "## 测量覆盖",
        "",
        f"- 运行数：{summary.coverage.runs}",
        f"- usage 未知：{summary.coverage.unknown_usage}"
        f"（比例 {value(summary.coverage.unknown_usage_rate)}）",
        f"- 已开始未完成尝试：{summary.coverage.incomplete_attempts}",
        f"- 清理失败：{summary.coverage.cleanup_failed}",
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
        "- 百分位为最近秩（nearest-rank），返回的值一定来自真实观测。",
        "- 每成功任务成本使用双方全部已配对运行（含失败）；任一侧 token 未知即 null。",
        "- 测量覆盖与安全门禁分开报告：未知 usage 削弱成本结论，不等于不安全。",
        "- 真实语义质量与误拒由 S5 盲化标注给出；未运行 live 时只有流程结论。",
        "",
    ])
    return "\n".join(lines)
