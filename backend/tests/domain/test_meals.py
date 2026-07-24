from decimal import Decimal

import pytest

from backend.domain.meals import (
    FoodDefinition,
    FoodPortion,
    MealDomainError,
    portion_from_food,
)


def test_food_portion_scales_per_100g_nutrients():
    food = FoodDefinition(
        name="Cooked rice",
        basis_type="per_100g",
        basis_amount=100,
        unit="g",
        calories=116,
        carbs=25.9,
        protein=2.6,
        fat=0.3,
        source="public",
    )

    portion = portion_from_food(food, amount=150, unit="g")

    assert portion.calories == 174.0
    assert portion.carbs == 38.9
    assert portion.protein == 3.9
    assert portion.fat == 0.5


@pytest.mark.parametrize(
    ("basis_type", "definition_unit", "portion_unit"),
    [
        ("per_100g", "g", "ml"),
        ("per_100ml", "ml", "g"),
        ("per_serving", "bowl", "serving"),
    ],
)
def test_food_portion_rejects_units_incompatible_with_basis(
    basis_type,
    definition_unit,
    portion_unit,
):
    food = FoodDefinition(
        name="Test food",
        basis_type=basis_type,
        basis_amount=100,
        unit=definition_unit,
        calories=100,
        carbs=10,
        protein=5,
        fat=2,
        source="public",
    )

    with pytest.raises(MealDomainError) as raised:
        portion_from_food(food, amount=50, unit=portion_unit)

    assert raised.value.code == "FOOD_UNIT_INCOMPATIBLE"


@pytest.mark.parametrize(
    "basis_amount",
    [0, -1, float("nan"), float("inf"), float("-inf")],
)
def test_food_definition_requires_positive_finite_basis_amount(basis_amount):
    with pytest.raises(MealDomainError) as raised:
        FoodDefinition(
            name="Test food",
            basis_type="per_100g",
            basis_amount=basis_amount,
            unit="g",
            calories=100,
            carbs=10,
            protein=5,
            fat=2,
            source="public",
        )

    assert raised.value.code == "FOOD_BASIS_AMOUNT_INVALID"


@pytest.mark.parametrize(
    "amount",
    [0, -1, float("nan"), float("inf"), float("-inf")],
)
def test_food_portion_requires_positive_finite_amount(amount):
    food = FoodDefinition(
        name="Test food",
        basis_type="per_serving",
        basis_amount=1,
        unit="bowl",
        calories=100,
        carbs=10,
        protein=5,
        fat=2,
        source="public",
    )

    with pytest.raises(MealDomainError) as raised:
        portion_from_food(food, amount=amount, unit="bowl")

    assert raised.value.code == "FOOD_PORTION_AMOUNT_INVALID"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("name", "", "FOOD_NAME_REQUIRED"),
        ("name", "   ", "FOOD_NAME_REQUIRED"),
        ("basis_type", "unknown", "FOOD_BASIS_TYPE_INVALID"),
        ("basis_type", [], "FOOD_BASIS_TYPE_INVALID"),
        ("unit", "", "FOOD_UNIT_REQUIRED"),
        ("unit", "   ", "FOOD_UNIT_REQUIRED"),
        ("source", "unknown", "FOOD_SOURCE_INVALID"),
        ("source", {}, "FOOD_SOURCE_INVALID"),
        ("calories", None, "FOOD_NUTRIENT_INVALID"),
        ("calories", "100", "FOOD_NUTRIENT_INVALID"),
        ("calories", Decimal("100"), "FOOD_NUTRIENT_INVALID"),
        ("carbs", -1, "FOOD_NUTRIENT_INVALID"),
        ("protein", float("nan"), "FOOD_NUTRIENT_INVALID"),
        ("fat", float("inf"), "FOOD_NUTRIENT_INVALID"),
    ],
)
def test_food_definition_requires_complete_valid_fields(field, value, code):
    values = {
        "name": "Test food",
        "basis_type": "per_100g",
        "basis_amount": 100,
        "unit": "g",
        "calories": 100,
        "carbs": 10,
        "protein": 5,
        "fat": 2,
        "source": "user_custom",
    }
    values[field] = value

    with pytest.raises(MealDomainError) as raised:
        FoodDefinition(**values)

    assert raised.value.code == code


def test_food_portion_is_an_immutable_snapshot():
    food = FoodDefinition(
        name="Milk",
        basis_type="per_100ml",
        basis_amount=100,
        unit="ml",
        calories=61,
        carbs=4.8,
        protein=3.2,
        fat=3.3,
        source="public",
    )

    portion = portion_from_food(food, amount=250, unit="ml")

    assert portion.food_name == "Milk"
    assert portion.amount == 250
    assert portion.unit == "ml"
    assert portion.basis_type == "per_100ml"
    assert portion.source == "public"
    assert portion.calories == 152.5
    with pytest.raises(AttributeError):
        portion.calories = 0
    with pytest.raises(AttributeError):
        food.name = "Changed"


def test_food_portion_scales_per_serving_nutrients():
    food = FoodDefinition(
        name="Protein bar",
        basis_type="per_serving",
        basis_amount=1,
        unit="bar",
        calories=210,
        carbs=24,
        protein=20,
        fat=6,
        source="public",
    )

    portion = portion_from_food(food, amount=1.5, unit="bar")

    assert portion.calories == 315.0
    assert portion.carbs == 36.0
    assert portion.protein == 30.0
    assert portion.fat == 9.0


@pytest.mark.parametrize(
    ("basis_type", "unit"),
    [("per_100g", "ml"), ("per_100ml", "g")],
)
def test_food_definition_rejects_unit_incompatible_with_basis(
    basis_type,
    unit,
):
    with pytest.raises(MealDomainError) as raised:
        FoodDefinition(
            name="Test food",
            basis_type=basis_type,
            basis_amount=100,
            unit=unit,
            calories=100,
            carbs=10,
            protein=5,
            fat=2,
            source="public",
        )

    assert raised.value.code == "FOOD_UNIT_INCOMPATIBLE"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("food_name", "", "FOOD_NAME_REQUIRED"),
        ("amount", 0, "FOOD_PORTION_AMOUNT_INVALID"),
        ("amount", float("inf"), "FOOD_PORTION_AMOUNT_INVALID"),
        ("unit", "", "FOOD_UNIT_REQUIRED"),
        ("unit", "ml", "FOOD_UNIT_INCOMPATIBLE"),
        ("basis_type", "unknown", "FOOD_BASIS_TYPE_INVALID"),
        ("basis_type", [], "FOOD_BASIS_TYPE_INVALID"),
        ("source", "unknown", "FOOD_SOURCE_INVALID"),
        ("source", {}, "FOOD_SOURCE_INVALID"),
        ("calories", -1, "FOOD_NUTRIENT_INVALID"),
        ("carbs", None, "FOOD_NUTRIENT_INVALID"),
    ],
)
def test_food_portion_constructor_enforces_snapshot_invariants(
    field,
    value,
    code,
):
    values = {
        "food_name": "Test food",
        "amount": 100,
        "unit": "g",
        "basis_type": "per_100g",
        "calories": 100,
        "carbs": 10,
        "protein": 5,
        "fat": 2,
        "source": "public",
    }
    values[field] = value

    with pytest.raises(MealDomainError) as raised:
        FoodPortion(**values)

    assert raised.value.code == code


def test_food_portion_translates_decimal_scaling_failure_to_domain_error():
    food = FoodDefinition(
        name="Oversized value",
        basis_type="per_100g",
        basis_amount=100,
        unit="g",
        calories=1e28,
        carbs=0,
        protein=0,
        fat=0,
        source="public",
    )

    with pytest.raises(MealDomainError) as raised:
        portion_from_food(food, amount=100, unit="g")

    assert raised.value.code == "FOOD_NUTRIENT_SCALE_INVALID"
