from dataclasses import replace
from decimal import Decimal

import pytest

from backend.domain.profile_targets import (
    DailyTargets,
    ProfileInput,
    TargetDomainError,
    calculate_daily_targets,
    evaluate_manual_targets,
)


def test_calculate_daily_targets_uses_approved_formula():
    profile = ProfileInput(
        age=30,
        height_cm=175,
        weight_kg=70,
        energy_parameter="male",
        activity_level="moderate",
        auto_target_disabled=False,
        safety_conditions=(),
    )

    result = calculate_daily_targets(profile, "fat_loss")

    assert result.formula_version == "mifflin_st_jeor_v1"
    assert result.calories == 2172
    assert result.protein == 126
    assert result.fat == 56
    assert result.carbs == 291


def test_manual_daily_targets_do_not_claim_a_formula_version():
    manual = DailyTargets(calories=2000, carbs=250, protein=125, fat=55)

    assert manual.formula_version is None


@pytest.mark.parametrize(
    ("energy_parameter", "activity_level", "goal", "expected"),
    [
        ("male", "sedentary", "fat_loss", (1682, 169, 126, 56)),
        ("male", "sedentary", "maintenance", (1979, 257, 112, 56)),
        ("male", "sedentary", "muscle_gain", (2176, 292, 126, 56)),
        ("male", "light", "fat_loss", (1927, 230, 126, 56)),
        ("male", "light", "maintenance", (2267, 329, 112, 56)),
        ("male", "light", "muscle_gain", (2494, 372, 126, 56)),
        ("male", "moderate", "fat_loss", (2172, 291, 126, 56)),
        ("male", "moderate", "maintenance", (2556, 401, 112, 56)),
        ("male", "moderate", "muscle_gain", (2811, 451, 126, 56)),
        ("male", "high", "fat_loss", (2417, 352, 126, 56)),
        ("male", "high", "maintenance", (2844, 473, 112, 56)),
        ("male", "high", "muscle_gain", (3129, 530, 126, 56)),
        ("female", "sedentary", "fat_loss", (1512, 126, 126, 56)),
        ("female", "sedentary", "maintenance", (1779, 207, 112, 56)),
        ("female", "sedentary", "muscle_gain", (1957, 237, 126, 56)),
        ("female", "light", "fat_loss", (1733, 181, 126, 56)),
        ("female", "light", "maintenance", (2039, 272, 112, 56)),
        ("female", "light", "muscle_gain", (2243, 309, 126, 56)),
        ("female", "moderate", "fat_loss", (1954, 237, 126, 56)),
        ("female", "moderate", "maintenance", (2298, 337, 112, 56)),
        ("female", "moderate", "muscle_gain", (2528, 380, 126, 56)),
        ("female", "high", "fat_loss", (2174, 292, 126, 56)),
        ("female", "high", "maintenance", (2558, 402, 112, 56)),
        ("female", "high", "muscle_gain", (2814, 452, 126, 56)),
        ("neutral", "sedentary", "fat_loss", (1597, 147, 126, 56)),
        ("neutral", "sedentary", "maintenance", (1879, 232, 112, 56)),
        ("neutral", "sedentary", "muscle_gain", (2067, 265, 126, 56)),
        ("neutral", "light", "fat_loss", (1830, 206, 126, 56)),
        ("neutral", "light", "maintenance", (2153, 300, 112, 56)),
        ("neutral", "light", "muscle_gain", (2368, 340, 126, 56)),
        ("neutral", "moderate", "fat_loss", (2063, 264, 126, 56)),
        ("neutral", "moderate", "maintenance", (2427, 369, 112, 56)),
        ("neutral", "moderate", "muscle_gain", (2670, 416, 126, 56)),
        ("neutral", "high", "fat_loss", (2296, 322, 126, 56)),
        ("neutral", "high", "maintenance", (2701, 437, 112, 56)),
        ("neutral", "high", "muscle_gain", (2971, 491, 126, 56)),
    ],
)
def test_calculate_daily_targets_covers_all_approved_parameters(
    energy_parameter, activity_level, goal, expected
):
    result = calculate_daily_targets(
        ProfileInput(
            age=30,
            height_cm=175,
            weight_kg=70,
            energy_parameter=energy_parameter,
            activity_level=activity_level,
        ),
        goal,
    )

    assert (result.calories, result.carbs, result.protein, result.fat) == expected


@pytest.mark.parametrize(
    ("energy_parameter", "expected_floor"),
    [("male", 1500), ("female", 1200), ("neutral", 1350)],
)
def test_calculate_daily_targets_applies_energy_parameter_floor(
    energy_parameter, expected_floor
):
    result = calculate_daily_targets(
        ProfileInput(
            age=90,
            height_cm=120,
            weight_kg=31,
            energy_parameter=energy_parameter,
            activity_level="sedentary",
        ),
        "fat_loss",
    )

    assert result.calories == expected_floor


@pytest.mark.parametrize(
    "profile",
    [
        ProfileInput(17, 175, 70, "male", "moderate"),
        ProfileInput(30, 175, 70, "male", "moderate", auto_target_disabled=True),
        ProfileInput(
            30,
            175,
            70,
            "male",
            "moderate",
            safety_conditions=("pregnancy",),
        ),
    ],
)
def test_calculate_daily_targets_rejects_automatic_calculation_restrictions(profile):
    with pytest.raises(TargetDomainError) as raised:
        calculate_daily_targets(profile, "maintenance")

    assert raised.value.code == "TARGET_CALCULATION_RESTRICTED"


def test_calculate_daily_targets_rejects_results_outside_manual_hard_ranges():
    profile = ProfileInput(18, 230, 300, "male", "high")

    with pytest.raises(TargetDomainError) as raised:
        calculate_daily_targets(profile, "muscle_gain")

    assert raised.value.code == "TARGET_OUT_OF_RANGE"


@pytest.mark.parametrize(
    ("field", "minimum", "maximum"),
    [
        ("calories", 800, 6000),
        ("carbs", 0, 1000),
        ("protein", 20, 400),
        ("fat", 10, 300),
    ],
)
def test_evaluate_manual_targets_accepts_inclusive_hard_boundaries(
    field, minimum, maximum
):
    baseline = DailyTargets(calories=2000, carbs=250, protein=125, fat=55)

    evaluate_manual_targets(replace(baseline, **{field: minimum}), baseline)
    evaluate_manual_targets(replace(baseline, **{field: maximum}), baseline)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("calories", 799),
        ("calories", 6001),
        ("carbs", -1),
        ("carbs", 1001),
        ("protein", 19),
        ("protein", 401),
        ("fat", 9),
        ("fat", 301),
    ],
)
def test_evaluate_manual_targets_rejects_values_outside_hard_ranges(field, value):
    baseline = DailyTargets(calories=2000, carbs=250, protein=125, fat=55)

    with pytest.raises(TargetDomainError) as raised:
        evaluate_manual_targets(replace(baseline, **{field: value}), baseline)

    assert raised.value.code == "TARGET_OUT_OF_RANGE"


def test_evaluate_manual_targets_requires_confirmation_for_baseline_deviation():
    baseline = DailyTargets(calories=2000, carbs=250, protein=125, fat=55)
    manual = DailyTargets(calories=2500, carbs=375, protein=125, fat=55)

    result = evaluate_manual_targets(manual, baseline)

    assert result.requires_confirmation is True
    assert result.warnings == ("TARGET_BASELINE_DEVIATION",)


def test_evaluate_manual_targets_requires_confirmation_for_macro_energy_mismatch():
    baseline = DailyTargets(calories=2000, carbs=250, protein=125, fat=55)
    manual = DailyTargets(calories=2000, carbs=300, protein=150, fat=66)

    result = evaluate_manual_targets(manual, baseline)

    assert result.requires_confirmation is True
    assert result.warnings == ("TARGET_MACRO_ENERGY_MISMATCH",)


def test_calculate_daily_targets_rounds_protein_half_up():
    result = calculate_daily_targets(
        ProfileInput(30, 175, 30.3125, "male", "moderate"),
        "maintenance",
    )

    assert Decimal("30.3125") * Decimal("1.6") == Decimal("48.50000")
    assert result.protein == 49


def test_calculate_daily_targets_rounds_fat_half_up():
    result = calculate_daily_targets(
        ProfileInput(30, 175, 30.625, "male", "moderate"),
        "maintenance",
    )

    assert Decimal("30.625") * Decimal("0.8") == Decimal("24.5000")
    assert result.fat == 25


def test_calculate_daily_targets_rounds_calorie_even_tie_half_up():
    result = calculate_daily_targets(
        ProfileInput(30, 175, 64.725, "male", "light"),
        "maintenance",
    )

    assert result.rationale is not None
    raw_calories = result.rationale.bmr * result.rationale.activity_factor
    assert raw_calories == Decimal("2194.5000")
    assert result.calories == 2195


def test_calculate_daily_targets_rounds_carbohydrate_even_tie_half_up():
    result = calculate_daily_targets(
        ProfileInput(30, 175, 30.125, "male", "moderate"),
        "maintenance",
    )

    raw_carbs = Decimal(
        result.calories - result.protein * 4 - result.fat * 9
    ) / Decimal("4")
    assert raw_carbs == Decimal("382.5")
    assert result.carbs == 383


def test_evaluate_manual_targets_does_not_warn_at_exactly_ten_percent_mismatch():
    baseline = DailyTargets(calories=2000, carbs=250, protein=125, fat=55)
    manual = DailyTargets(calories=2000, carbs=300, protein=142, fat=48)

    result = evaluate_manual_targets(manual, baseline)

    assert manual.carbs * 4 + manual.protein * 4 + manual.fat * 9 == 2200
    assert result.requires_confirmation is False
    assert result.warnings == ()


def test_evaluate_manual_targets_returns_both_warnings_when_both_rules_apply():
    baseline = DailyTargets(calories=2000, carbs=250, protein=125, fat=55)
    manual = DailyTargets(calories=2500, carbs=250, protein=125, fat=55)

    result = evaluate_manual_targets(manual, baseline)

    assert result.requires_confirmation is True
    assert result.warnings == (
        "TARGET_BASELINE_DEVIATION",
        "TARGET_MACRO_ENERGY_MISMATCH",
    )


def test_evaluate_manual_targets_returns_no_warning_for_consistent_target():
    baseline = DailyTargets(calories=2000, carbs=250, protein=125, fat=55)

    result = evaluate_manual_targets(baseline, baseline)

    assert result.requires_confirmation is False
    assert result.warnings == ()
