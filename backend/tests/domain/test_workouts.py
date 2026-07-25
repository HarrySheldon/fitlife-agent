import pytest

from backend.domain.workouts import (
    StrengthSet,
    WorkoutDomainError,
    cardio_calories,
    compact_strength_sets,
    strength_calories,
)


def test_cardio_prefers_device_calories_without_marking_estimate():
    result = cardio_calories(
        duration_min=30,
        device_calories=245,
        met=8,
        weight_kg=70,
    )

    assert result.calories == 245
    assert result.is_estimate is False
    assert result.method == "device"
    assert result.formula_version is None


def test_cardio_uses_versioned_met_formula_when_device_value_is_missing():
    result = cardio_calories(
        duration_min=30,
        device_calories=None,
        met=8,
        weight_kg=70,
    )

    assert result.calories == 294.0
    assert result.is_estimate is True
    assert result.method == "met"
    assert result.formula_version == "met-kcal-v1"
    assert result.inputs == {"duration_min": 30.0, "met": 8.0, "weight_kg": 70.0}


def test_strength_calories_require_duration_before_returning_estimate():
    assert (
        strength_calories(
            duration_min=None,
            intensity="medium",
            weight_kg=70,
        )
        is None
    )


@pytest.mark.parametrize(
    ("intensity", "expected"),
    [("low", 128.6), ("medium", 183.8), ("high", 220.5)],
)
def test_strength_calories_use_versioned_intensity_met(
    intensity,
    expected,
):
    result = strength_calories(
        duration_min=30,
        intensity=intensity,
        weight_kg=70,
    )

    assert result.calories == expected
    assert result.is_estimate is True
    assert result.method == "strength_met"
    assert result.formula_version == "strength-met-v1"
    assert result.inputs["intensity"] == intensity


def test_compact_strength_sets_expand_to_immutable_ordered_sets():
    sets = compact_strength_sets(
        set_count=3,
        reps=8,
        load_kg=60,
        bodyweight=False,
    )

    assert sets == (
        StrengthSet(set_number=1, reps=8, load_kg=60, bodyweight=False),
        StrengthSet(set_number=2, reps=8, load_kg=60, bodyweight=False),
        StrengthSet(set_number=3, reps=8, load_kg=60, bodyweight=False),
    )


def test_bodyweight_sets_do_not_require_external_load():
    sets = compact_strength_sets(
        set_count=2,
        reps=12,
        load_kg=None,
        bodyweight=True,
    )

    assert all(item.bodyweight for item in sets)
    assert all(item.load_kg is None for item in sets)


@pytest.mark.parametrize(
    ("call", "code"),
    [
        (
            lambda: cardio_calories(
                duration_min=0,
                device_calories=None,
                met=8,
                weight_kg=70,
            ),
            "WORKOUT_DURATION_INVALID",
        ),
        (
            lambda: cardio_calories(
                duration_min=30,
                device_calories=None,
                met=None,
                weight_kg=70,
            ),
            "WORKOUT_MET_REQUIRED",
        ),
        (
            lambda: strength_calories(
                duration_min=30,
                intensity=None,
                weight_kg=70,
            ),
            "WORKOUT_INTENSITY_REQUIRED",
        ),
        (
            lambda: compact_strength_sets(
                set_count=0,
                reps=8,
                load_kg=60,
                bodyweight=False,
            ),
            "STRENGTH_SET_COUNT_INVALID",
        ),
        (
            lambda: compact_strength_sets(
                set_count=3,
                reps=0,
                load_kg=60,
                bodyweight=False,
            ),
            "STRENGTH_REPS_INVALID",
        ),
        (
            lambda: compact_strength_sets(
                set_count=3,
                reps=8,
                load_kg=-1,
                bodyweight=False,
            ),
            "STRENGTH_LOAD_INVALID",
        ),
    ],
)
def test_workout_domain_rejects_invalid_values(call, code):
    with pytest.raises(WorkoutDomainError) as raised:
        call()

    assert raised.value.code == code
