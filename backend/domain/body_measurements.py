"""Deterministic body measurement time-series domain models and trend metrics."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class BodyMeasurement:
    id: str
    user_id: str
    measured_date: str
    measured_at: str
    weight_kg: float | None = None
    body_fat_pct: float | None = None
    waist_cm: float | None = None
    chest_cm: float | None = None
    hip_cm: float | None = None
    note: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "measured_date": self.measured_date,
            "measured_at": self.measured_at,
            "weight_kg": self.weight_kg,
            "body_fat_pct": self.body_fat_pct,
            "waist_cm": self.waist_cm,
            "chest_cm": self.chest_cm,
            "hip_cm": self.hip_cm,
            "note": self.note,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class BodyTrendPoint:
    date: str
    weight_kg: float | None
    moving_avg_7d: float | None
    body_fat_pct: float | None
    waist_cm: float | None
    chest_cm: float | None
    hip_cm: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "date": self.date,
            "weight_kg": self.weight_kg,
            "moving_avg_7d": self.moving_avg_7d,
            "body_fat_pct": self.body_fat_pct,
            "waist_cm": self.waist_cm,
            "chest_cm": self.chest_cm,
            "hip_cm": self.hip_cm,
        }


@dataclass(frozen=True)
class BodyMeasurementSummary:
    count: int
    weight_count: int
    start_weight_kg: float | None
    latest_weight_kg: float | None
    latest_measured_date: str | None
    latest_7d_avg_kg: float | None
    total_change_kg: float | None
    weekly_rate_kg: float | None
    target_weight_kg: float | None
    distance_to_target_kg: float | None
    latest_body_fat_pct: float | None
    latest_waist_cm: float | None
    trend: tuple[BodyTrendPoint, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "count": self.count,
            "weight_count": self.weight_count,
            "start_weight_kg": self.start_weight_kg,
            "latest_weight_kg": self.latest_weight_kg,
            "latest_measured_date": self.latest_measured_date,
            "latest_7d_avg_kg": self.latest_7d_avg_kg,
            "total_change_kg": self.total_change_kg,
            "weekly_rate_kg": self.weekly_rate_kg,
            "target_weight_kg": self.target_weight_kg,
            "distance_to_target_kg": self.distance_to_target_kg,
            "latest_body_fat_pct": self.latest_body_fat_pct,
            "latest_waist_cm": self.latest_waist_cm,
            "trend": [point.to_dict() for point in self.trend],
        }


def compute_body_summary(
    measurements: list[BodyMeasurement] | tuple[BodyMeasurement, ...],
    *,
    target_weight_kg: float | None = None,
) -> BodyMeasurementSummary:
    """Compute chronological daily trend, 7-day moving average, and 4-week change rate."""
    if not measurements:
        return BodyMeasurementSummary(
            count=0,
            weight_count=0,
            start_weight_kg=None,
            latest_weight_kg=None,
            latest_measured_date=None,
            latest_7d_avg_kg=None,
            total_change_kg=None,
            weekly_rate_kg=None,
            target_weight_kg=target_weight_kg,
            distance_to_target_kg=None,
            latest_body_fat_pct=None,
            latest_waist_cm=None,
            trend=(),
        )

    ordered = sorted(measurements, key=lambda item: (item.measured_date, item.measured_at, item.id))

    # Merge multiple readings on the same date, keeping the latest non-null value for each metric.
    by_date: dict[str, dict[str, float | None]] = {}
    for row in ordered:
        bucket = by_date.setdefault(
            row.measured_date,
            {
                "weight_kg": None,
                "body_fat_pct": None,
                "waist_cm": None,
                "chest_cm": None,
                "hip_cm": None,
            },
        )
        for field in ("weight_kg", "body_fat_pct", "waist_cm", "chest_cm", "hip_cm"):
            value = getattr(row, field)
            if value is not None:
                bucket[field] = float(value)

    dates = sorted(by_date.keys())
    parsed_dates = {d: date.fromisoformat(d) for d in dates}

    weight_series: list[tuple[date, float]] = []
    trend_points: list[BodyTrendPoint] = []
    for day_str in dates:
        bucket = by_date[day_str]
        day = parsed_dates[day_str]
        weight = bucket["weight_kg"]
        if weight is not None:
            weight_series.append((day, weight))
        window_start = day - timedelta(days=6)
        window_weights = [w for d, w in weight_series if window_start <= d <= day]
        moving_avg = round(sum(window_weights) / len(window_weights), 2) if len(window_weights) >= 2 else (
            round(window_weights[0], 2) if len(window_weights) == 1 and weight is not None else None
        )
        trend_points.append(
            BodyTrendPoint(
                date=day_str,
                weight_kg=round(weight, 2) if weight is not None else None,
                moving_avg_7d=moving_avg,
                body_fat_pct=round(bucket["body_fat_pct"], 2) if bucket["body_fat_pct"] is not None else None,
                waist_cm=round(bucket["waist_cm"], 2) if bucket["waist_cm"] is not None else None,
                chest_cm=round(bucket["chest_cm"], 2) if bucket["chest_cm"] is not None else None,
                hip_cm=round(bucket["hip_cm"], 2) if bucket["hip_cm"] is not None else None,
            )
        )

    start_weight = round(weight_series[0][1], 2) if weight_series else None
    latest_weight = round(weight_series[-1][1], 2) if weight_series else None
    latest_date = dates[-1]
    latest_7d_avg = next((p.moving_avg_7d for p in reversed(trend_points) if p.moving_avg_7d is not None), None)
    total_change = round(latest_weight - start_weight, 2) if (latest_weight is not None and start_weight is not None) else None

    weekly_rate: float | None = None
    if len(weight_series) >= 2:
        latest_day, latest_val = weight_series[-1]
        cutoff = latest_day - timedelta(days=28)
        recent = [(d, w) for d, w in weight_series if d >= cutoff]
        if len(recent) >= 2:
            span_days = (recent[-1][0] - recent[0][0]).days
            if span_days >= 3:
                weekly_rate = round((recent[-1][1] - recent[0][1]) * 7.0 / span_days, 2)
        else:
            span_days = (weight_series[-1][0] - weight_series[0][0]).days
            if span_days >= 3:
                weekly_rate = round((latest_val - weight_series[0][1]) * 7.0 / span_days, 2)

    distance_to_target = (
        round(latest_weight - target_weight_kg, 2)
        if latest_weight is not None and target_weight_kg is not None
        else None
    )
    latest_body_fat = next((p.body_fat_pct for p in reversed(trend_points) if p.body_fat_pct is not None), None)
    latest_waist = next((p.waist_cm for p in reversed(trend_points) if p.waist_cm is not None), None)

    return BodyMeasurementSummary(
        count=len(ordered),
        weight_count=len(weight_series),
        start_weight_kg=start_weight,
        latest_weight_kg=latest_weight,
        latest_measured_date=latest_date,
        latest_7d_avg_kg=latest_7d_avg,
        total_change_kg=total_change,
        weekly_rate_kg=weekly_rate,
        target_weight_kg=round(target_weight_kg, 2) if target_weight_kg is not None else None,
        distance_to_target_kg=distance_to_target,
        latest_body_fat_pct=latest_body_fat,
        latest_waist_cm=latest_waist,
        trend=tuple(trend_points),
    )
