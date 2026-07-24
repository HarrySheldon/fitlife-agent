from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, DecimalException, InvalidOperation, ROUND_HALF_UP
from typing import Literal


BasisType = Literal["per_100g", "per_100ml", "per_serving"]
FoodSource = Literal[
    "public",
    "user_custom",
    "agent_estimate",
    "legacy_import",
]
_BASIS_TYPES: frozenset[str] = frozenset(
    {"per_100g", "per_100ml", "per_serving"}
)
_FOOD_SOURCES: frozenset[str] = frozenset(
    {"public", "user_custom", "agent_estimate", "legacy_import"}
)


class MealDomainError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class FoodDefinition:
    name: str
    basis_type: BasisType
    basis_amount: float
    unit: str
    calories: float
    carbs: float
    protein: float
    fat: float
    source: FoodSource

    def __post_init__(self) -> None:
        _validate_food_identity(
            name=self.name,
            basis_type=self.basis_type,
            unit=self.unit,
            source=self.source,
        )
        _validate_basis_unit(self.basis_type, self.unit)
        _require_positive_finite(
            self.basis_amount,
            "FOOD_BASIS_AMOUNT_INVALID",
        )
        for nutrient in (
            self.calories,
            self.carbs,
            self.protein,
            self.fat,
        ):
            _require_nonnegative_finite(nutrient, "FOOD_NUTRIENT_INVALID")


@dataclass(frozen=True)
class FoodPortion:
    food_name: str
    amount: float
    unit: str
    basis_type: BasisType
    calories: float
    carbs: float
    protein: float
    fat: float
    source: FoodSource

    def __post_init__(self) -> None:
        _validate_food_identity(
            name=self.food_name,
            basis_type=self.basis_type,
            unit=self.unit,
            source=self.source,
        )
        _validate_basis_unit(self.basis_type, self.unit)
        _require_positive_finite(
            self.amount,
            "FOOD_PORTION_AMOUNT_INVALID",
        )
        for nutrient in (
            self.calories,
            self.carbs,
            self.protein,
            self.fat,
        ):
            _require_nonnegative_finite(nutrient, "FOOD_NUTRIENT_INVALID")


def portion_from_food(
    food: FoodDefinition,
    *,
    amount: float,
    unit: str,
) -> FoodPortion:
    _require_positive_finite(amount, "FOOD_PORTION_AMOUNT_INVALID")
    validate_compatible_unit(food, unit)
    try:
        factor = Decimal(str(amount)) / Decimal(str(food.basis_amount))
    except DecimalException:
        raise MealDomainError("FOOD_PORTION_SCALE_INVALID") from None
    return FoodPortion(
        food_name=food.name,
        amount=amount,
        unit=unit,
        basis_type=food.basis_type,
        calories=_scaled(food.calories, factor),
        carbs=_scaled(food.carbs, factor),
        protein=_scaled(food.protein, factor),
        fat=_scaled(food.fat, factor),
        source=food.source,
    )


def validate_compatible_unit(food: FoodDefinition, unit: str) -> None:
    expected_unit = {
        "per_100g": "g",
        "per_100ml": "ml",
        "per_serving": food.unit,
    }.get(food.basis_type)
    if unit != expected_unit:
        raise MealDomainError("FOOD_UNIT_INCOMPATIBLE")


def _validate_food_identity(
    *,
    name: object,
    basis_type: object,
    unit: object,
    source: object,
) -> None:
    if not isinstance(name, str) or not name.strip():
        raise MealDomainError("FOOD_NAME_REQUIRED")
    if not isinstance(basis_type, str) or basis_type not in _BASIS_TYPES:
        raise MealDomainError("FOOD_BASIS_TYPE_INVALID")
    if not isinstance(unit, str) or not unit.strip():
        raise MealDomainError("FOOD_UNIT_REQUIRED")
    if not isinstance(source, str) or source not in _FOOD_SOURCES:
        raise MealDomainError("FOOD_SOURCE_INVALID")


def _validate_basis_unit(basis_type: object, unit: str) -> None:
    expected_unit = {
        "per_100g": "g",
        "per_100ml": "ml",
    }.get(basis_type)
    if expected_unit is not None and unit != expected_unit:
        raise MealDomainError("FOOD_UNIT_INCOMPATIBLE")


def _scaled(value: float, factor: Decimal) -> float:
    try:
        return float(
            (Decimal(str(value)) * factor).quantize(
                Decimal("0.1"),
                rounding=ROUND_HALF_UP,
            )
        )
    except (DecimalException, OverflowError):
        raise MealDomainError("FOOD_NUTRIENT_SCALE_INVALID") from None


def _require_positive_finite(value: object, code: str) -> None:
    number = _decimal(value, code)
    if number <= 0:
        raise MealDomainError(code)


def _require_nonnegative_finite(value: object, code: str) -> None:
    number = _decimal(value, code)
    if number < 0:
        raise MealDomainError(code)


def _decimal(value: object, code: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MealDomainError(code)
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise MealDomainError(code) from None
    if not number.is_finite():
        raise MealDomainError(code)
    return number
