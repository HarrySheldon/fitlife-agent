from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal


EnergyParameter = Literal["male", "female", "neutral"]
ActivityLevel = Literal["sedentary", "light", "moderate", "high"]
OverallGoal = Literal["fat_loss", "maintenance", "muscle_gain"]

FORMULA_VERSION = "mifflin_st_jeor_v1"

_ENERGY_CONSTANTS: dict[EnergyParameter, Decimal] = {
    "male": Decimal("5"),
    "female": Decimal("-161"),
    "neutral": Decimal("-78"),
}
_ACTIVITY_FACTORS: dict[ActivityLevel, Decimal] = {
    "sedentary": Decimal("1.2"),
    "light": Decimal("1.375"),
    "moderate": Decimal("1.55"),
    "high": Decimal("1.725"),
}
_GOAL_ADJUSTMENTS: dict[OverallGoal, Decimal] = {
    "fat_loss": Decimal("0.85"),
    "maintenance": Decimal("1"),
    "muscle_gain": Decimal("1.10"),
}
_ENERGY_FLOORS: dict[EnergyParameter, Decimal] = {
    "male": Decimal("1500"),
    "female": Decimal("1200"),
    "neutral": Decimal("1350"),
}
_TARGET_RANGES = {
    "calories": (800, 6000),
    "carbs": (0, 1000),
    "protein": (20, 400),
    "fat": (10, 300),
}


class TargetDomainError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ProfileInput:
    age: int
    height_cm: int | float
    weight_kg: int | float
    energy_parameter: EnergyParameter
    activity_level: ActivityLevel
    auto_target_disabled: bool = False
    safety_conditions: tuple[str, ...] = ()


@dataclass(frozen=True)
class TargetRationale:
    bmr: Decimal
    activity_factor: Decimal
    goal_adjustment: Decimal
    calorie_floor: int
    protein_grams_per_kg: Decimal
    fat_grams_per_kg: Decimal


@dataclass(frozen=True)
class DailyTargets:
    calories: int
    carbs: int
    protein: int
    fat: int
    formula_version: str | None = None
    rationale: TargetRationale | None = None


@dataclass(frozen=True)
class TargetValidation:
    warnings: tuple[str, ...]
    requires_confirmation: bool


def calculate_daily_targets(profile: ProfileInput, goal: OverallGoal) -> DailyTargets:
    if (
        profile.age < 18
        or profile.auto_target_disabled
        or bool(profile.safety_conditions)
    ):
        raise TargetDomainError("TARGET_CALCULATION_RESTRICTED")

    weight = Decimal(str(profile.weight_kg))
    height = Decimal(str(profile.height_cm))
    bmr = (
        Decimal("10") * weight
        + Decimal("6.25") * height
        - Decimal("5") * Decimal(profile.age)
        + _ENERGY_CONSTANTS[profile.energy_parameter]
    )
    activity_factor = _ACTIVITY_FACTORS[profile.activity_level]
    goal_adjustment = _GOAL_ADJUSTMENTS[goal]
    floor = _ENERGY_FLOORS[profile.energy_parameter]
    calories = _round(max(bmr * activity_factor * goal_adjustment, floor))
    protein_factor = Decimal("1.6") if goal == "maintenance" else Decimal("1.8")
    protein = _round(weight * protein_factor)
    fat = _round(weight * Decimal("0.8"))
    carbs = _round(
        (Decimal(calories) - Decimal(protein * 4) - Decimal(fat * 9))
        / Decimal("4")
    )
    result = DailyTargets(
        calories=calories,
        carbs=carbs,
        protein=protein,
        fat=fat,
        formula_version=FORMULA_VERSION,
        rationale=TargetRationale(
            bmr=bmr,
            activity_factor=activity_factor,
            goal_adjustment=goal_adjustment,
            calorie_floor=int(floor),
            protein_grams_per_kg=protein_factor,
            fat_grams_per_kg=Decimal("0.8"),
        ),
    )
    _require_hard_ranges(result)
    return result


def evaluate_manual_targets(
    manual: DailyTargets,
    baseline: DailyTargets,
) -> TargetValidation:
    _require_hard_ranges(manual)
    warnings: list[str] = []

    if any(
        _relative_deviation(getattr(manual, field), getattr(baseline, field))
        > Decimal("0.20")
        for field in _TARGET_RANGES
    ):
        warnings.append("TARGET_BASELINE_DEVIATION")

    macro_energy = Decimal(
        manual.carbs * 4 + manual.protein * 4 + manual.fat * 9
    )
    calorie_mismatch = abs(macro_energy - Decimal(manual.calories)) / Decimal(
        manual.calories
    )
    if calorie_mismatch > Decimal("0.10"):
        warnings.append("TARGET_MACRO_ENERGY_MISMATCH")

    return TargetValidation(
        warnings=tuple(warnings),
        requires_confirmation=bool(warnings),
    )


def _require_hard_ranges(targets: DailyTargets) -> None:
    for field, (minimum, maximum) in _TARGET_RANGES.items():
        if not minimum <= getattr(targets, field) <= maximum:
            raise TargetDomainError("TARGET_OUT_OF_RANGE")


def _relative_deviation(value: int, baseline: int) -> Decimal:
    if baseline == 0:
        return Decimal(0) if value == 0 else Decimal("Infinity")
    return abs(Decimal(value) - Decimal(baseline)) / Decimal(baseline)


def _round(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
