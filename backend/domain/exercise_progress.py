"""Deterministic strength exercise progression (PRs, estimated 1RM, volume)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrengthSetRow:
    log_date: str
    session_id: str
    catalog_exercise_id: str | None
    exercise_name: str
    primary_muscle: str
    reps: int
    load_kg: float | None
    bodyweight: bool


@dataclass(frozen=True)
class ExerciseSessionPoint:
    date: str
    session_id: str
    max_weight_kg: float | None
    estimated_1rm_kg: float | None
    total_volume_kg: float
    total_sets: int
    total_reps: int
    best_set_reps: int

    def to_dict(self) -> dict[str, object]:
        return {
            "date": self.date,
            "session_id": self.session_id,
            "max_weight_kg": self.max_weight_kg,
            "estimated_1rm_kg": self.estimated_1rm_kg,
            "total_volume_kg": self.total_volume_kg,
            "total_sets": self.total_sets,
            "total_reps": self.total_reps,
            "best_set_reps": self.best_set_reps,
        }


@dataclass(frozen=True)
class ExerciseProgressSummary:
    exercise_key: str
    catalog_exercise_id: str | None
    exercise_name: str
    primary_muscle: str
    session_count: int
    latest_date: str
    best_weight_kg: float | None
    best_1rm_kg: float | None
    best_volume_kg: float
    latest_weight_kg: float | None
    latest_1rm_kg: float | None
    delta_1rm_kg: float | None
    series: tuple[ExerciseSessionPoint, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "exercise_key": self.exercise_key,
            "catalog_exercise_id": self.catalog_exercise_id,
            "exercise_name": self.exercise_name,
            "primary_muscle": self.primary_muscle,
            "session_count": self.session_count,
            "latest_date": self.latest_date,
            "best_weight_kg": self.best_weight_kg,
            "best_1rm_kg": self.best_1rm_kg,
            "best_volume_kg": self.best_volume_kg,
            "latest_weight_kg": self.latest_weight_kg,
            "latest_1rm_kg": self.latest_1rm_kg,
            "delta_1rm_kg": self.delta_1rm_kg,
            "series": [point.to_dict() for point in self.series],
        }


def estimate_epley_1rm(load_kg: float | None, reps: int) -> float | None:
    """Epley 1RM estimate for loaded working sets up to 12 reps."""
    if load_kg is None or load_kg <= 0 or reps < 1 or reps > 12:
        return None
    if reps == 1:
        return round(load_kg, 2)
    return round(load_kg * (1.0 + reps / 30.0), 2)


def aggregate_exercise_progress(
    rows: list[StrengthSetRow] | tuple[StrengthSetRow, ...],
) -> tuple[ExerciseProgressSummary, ...]:
    """Group logged strength sets by exercise and compute per-session metrics & PRs."""
    by_exercise: dict[str, list[StrengthSetRow]] = {}
    for row in rows:
        key = row.catalog_exercise_id or f"name:{row.exercise_name.strip().lower()}"
        by_exercise.setdefault(key, []).append(row)

    summaries: list[ExerciseProgressSummary] = []
    for key, exercise_rows in by_exercise.items():
        latest_meta = max(exercise_rows, key=lambda r: (r.log_date, r.session_id))
        by_session: dict[tuple[str, str], list[StrengthSetRow]] = {}
        for row in exercise_rows:
            by_session.setdefault((row.log_date, row.session_id), []).append(row)

        points: list[ExerciseSessionPoint] = []
        for (log_date, session_id), session_sets in sorted(by_session.items()):
            loaded = [s for s in session_sets if s.load_kg is not None and s.load_kg > 0]
            max_weight = round(max((s.load_kg for s in loaded if s.load_kg is not None), default=0.0), 2) if loaded else None
            e1rms = [est for s in loaded if (est := estimate_epley_1rm(s.load_kg, s.reps)) is not None]
            best_e1rm = round(max(e1rms), 2) if e1rms else None
            volume = round(sum((s.load_kg or 0.0) * s.reps for s in session_sets), 2)
            total_reps = sum(s.reps for s in session_sets)
            best_reps = max(s.reps for s in session_sets)
            points.append(
                ExerciseSessionPoint(
                    date=log_date,
                    session_id=session_id,
                    max_weight_kg=max_weight,
                    estimated_1rm_kg=best_e1rm,
                    total_volume_kg=volume,
                    total_sets=len(session_sets),
                    total_reps=total_reps,
                    best_set_reps=best_reps,
                )
            )

        weights = [p.max_weight_kg for p in points if p.max_weight_kg is not None]
        one_rms = [p.estimated_1rm_kg for p in points if p.estimated_1rm_kg is not None]
        best_weight = max(weights) if weights else None
        best_1rm = max(one_rms) if one_rms else None
        best_volume = round(max(p.total_volume_kg for p in points), 2)
        latest_weight = points[-1].max_weight_kg
        latest_1rm = points[-1].estimated_1rm_kg
        delta_1rm = round(one_rms[-1] - one_rms[0], 2) if len(one_rms) >= 2 else None

        summaries.append(
            ExerciseProgressSummary(
                exercise_key=key,
                catalog_exercise_id=latest_meta.catalog_exercise_id,
                exercise_name=latest_meta.exercise_name,
                primary_muscle=latest_meta.primary_muscle,
                session_count=len(points),
                latest_date=points[-1].date,
                best_weight_kg=best_weight,
                best_1rm_kg=best_1rm,
                best_volume_kg=best_volume,
                latest_weight_kg=latest_weight,
                latest_1rm_kg=latest_1rm,
                delta_1rm_kg=delta_1rm,
                series=tuple(points),
            )
        )

    summaries.sort(key=lambda s: (-s.session_count, s.latest_date, s.exercise_name), reverse=False)
    # Sort most recent first when session_count ties
    summaries.sort(key=lambda s: (s.session_count, s.latest_date), reverse=True)
    return tuple(summaries)
