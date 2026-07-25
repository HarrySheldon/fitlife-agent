from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Literal


Intensity = Literal["low", "medium", "high"]
EstimateMethod = Literal["device", "met", "strength_met"]
_STRENGTH_MET: dict[str, Decimal] = {
    "low": Decimal("3.5"),
    "medium": Decimal("5.0"),
    "high": Decimal("6.0"),
}


class WorkoutDomainError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CalorieResult:
    calories: float
    is_estimate: bool
    method: EstimateMethod
    formula_version: str | None
    inputs: dict[str, object]


@dataclass(frozen=True)
class StrengthSet:
    set_number: int
    reps: int
    load_kg: float | None
    bodyweight: bool

    def __post_init__(self) -> None:
        _positive_integer(self.set_number, "STRENGTH_SET_NUMBER_INVALID")
        _positive_integer(self.reps, "STRENGTH_REPS_INVALID")
        if not isinstance(self.bodyweight, bool):
            raise WorkoutDomainError("STRENGTH_BODYWEIGHT_INVALID")
        if self.load_kg is not None:
            _nonnegative(self.load_kg, "STRENGTH_LOAD_INVALID")


def cardio_calories(
    *,
    duration_min: float,
    device_calories: float | None,
    met: float | None,
    weight_kg: float | None,
) -> CalorieResult:
    duration = _positive(duration_min, "WORKOUT_DURATION_INVALID")
    if device_calories is not None:
        device = _nonnegative(
            device_calories,
            "WORKOUT_DEVICE_CALORIES_INVALID",
        )
        return CalorieResult(
            calories=_rounded(device),
            is_estimate=False,
            method="device",
            formula_version=None,
            inputs={
                "device_calories": float(device),
                "duration_min": float(duration),
            },
        )
    if met is None:
        raise WorkoutDomainError("WORKOUT_MET_REQUIRED")
    if weight_kg is None:
        raise WorkoutDomainError("WORKOUT_WEIGHT_REQUIRED")
    met_value = _positive(met, "WORKOUT_MET_INVALID")
    weight = _positive(weight_kg, "WORKOUT_WEIGHT_INVALID")
    calories = met_value * Decimal("3.5") * weight / Decimal("200") * duration
    return CalorieResult(
        calories=_rounded(calories),
        is_estimate=True,
        method="met",
        formula_version="met-kcal-v1",
        inputs={
            "duration_min": float(duration),
            "met": float(met_value),
            "weight_kg": float(weight),
        },
    )


def strength_calories(
    *,
    duration_min: float | None,
    intensity: Intensity | None,
    weight_kg: float | None,
) -> CalorieResult | None:
    if duration_min is None:
        return None
    duration = _positive(duration_min, "WORKOUT_DURATION_INVALID")
    if intensity not in _STRENGTH_MET:
        raise WorkoutDomainError("WORKOUT_INTENSITY_REQUIRED")
    if weight_kg is None:
        raise WorkoutDomainError("WORKOUT_WEIGHT_REQUIRED")
    weight = _positive(weight_kg, "WORKOUT_WEIGHT_INVALID")
    met = _STRENGTH_MET[intensity]
    calories = met * Decimal("3.5") * weight / Decimal("200") * duration
    return CalorieResult(
        calories=_rounded(calories),
        is_estimate=True,
        method="strength_met",
        formula_version="strength-met-v1",
        inputs={
            "duration_min": float(duration),
            "intensity": intensity,
            "met": float(met),
            "weight_kg": float(weight),
        },
    )


def compact_strength_sets(
    *,
    set_count: int,
    reps: int,
    load_kg: float | None,
    bodyweight: bool,
) -> tuple[StrengthSet, ...]:
    count = _positive_integer(set_count, "STRENGTH_SET_COUNT_INVALID")
    repetitions = _positive_integer(reps, "STRENGTH_REPS_INVALID")
    if not isinstance(bodyweight, bool):
        raise WorkoutDomainError("STRENGTH_BODYWEIGHT_INVALID")
    if load_kg is not None:
        _nonnegative(load_kg, "STRENGTH_LOAD_INVALID")
    return tuple(
        StrengthSet(
            set_number=index,
            reps=repetitions,
            load_kg=load_kg,
            bodyweight=bodyweight,
        )
        for index in range(1, count + 1)
    )


def _positive(value: object, code: str) -> Decimal:
    number = _decimal(value, code)
    if number <= 0:
        raise WorkoutDomainError(code)
    return number


def _nonnegative(value: object, code: str) -> Decimal:
    number = _decimal(value, code)
    if number < 0:
        raise WorkoutDomainError(code)
    return number


def _positive_integer(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise WorkoutDomainError(code)
    return value


def _decimal(value: object, code: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WorkoutDomainError(code)
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise WorkoutDomainError(code) from None
    if not number.is_finite():
        raise WorkoutDomainError(code)
    return number


def _rounded(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
