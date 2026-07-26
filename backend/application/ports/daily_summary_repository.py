from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class NutritionSnapshot:
    calories: float
    carbs: float
    protein: float
    fat: float


@dataclass(frozen=True)
class DailyTargetSnapshot(NutritionSnapshot):
    id: str
    source: str
    effective_from: str


@dataclass(frozen=True)
class MealSummary:
    id: str
    name: str
    meal_type: str
    position: int
    item_count: int
    nutrition: NutritionSnapshot


@dataclass(frozen=True)
class WorkoutSummary:
    id: str
    title: str
    started_at: str | None
    duration_min: float | None
    intensity: str | None
    calories: float | None
    contains_estimates: bool
    strength_exercise_count: int
    strength_set_count: int
    cardio_item_count: int


@dataclass(frozen=True)
class DailySummary:
    date: str
    target: DailyTargetSnapshot | None
    consumed: NutritionSnapshot
    planned_meal_count: int
    recorded_meal_count: int
    meals: tuple[MealSummary, ...]
    workouts: tuple[WorkoutSummary, ...]


@runtime_checkable
class DailySummaryRepository(Protocol):
    def get_day(
        self,
        user_id: str,
        log_date: str,
        timezone_name: str,
    ) -> DailySummary: ...

    def set_planned_meal_count(
        self,
        user_id: str,
        log_date: str,
        planned_meal_count: int,
        timezone_name: str,
    ) -> DailySummary: ...
