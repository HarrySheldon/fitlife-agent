import pytest

from backend.domain.profile_targets import TargetDomainError
from backend.schemas import UserProfile
from backend.tools import target_suggestions
from backend.tools.target_suggestions import suggest_targets


def test_profile_accepts_v2_personalization_fields():
    profile = UserProfile(
        height_cm=178,
        weight_kg=82,
        age=28,
        gender="male",
        goal="fat_loss",
        weekly_training_frequency=4,
        allergies_or_restrictions=["peanut"],
        target_weight_kg=76,
        daily_calorie_target=2100,
        daily_protein_target=150,
        experience_level="novice",
        training_preference="mixed",
        target_mode="suggested",
    )

    assert profile.experience_level == "novice"
    assert profile.training_preference == "mixed"
    assert profile.target_mode == "suggested"


def test_target_suggestion_uses_goal_and_body_weight():
    profile = UserProfile(
        height_cm=178,
        weight_kg=82,
        age=28,
        gender="male",
        goal="fat_loss",
        weekly_training_frequency=4,
        target_weight_kg=76,
        daily_calorie_target=2100,
        daily_protein_target=150,
    )

    suggestion = suggest_targets(profile)

    assert suggestion.daily_calorie_target == 2368
    assert suggestion.daily_protein_target == 148
    assert suggestion.source == "system"
    assert "fat loss" in suggestion.rationale.lower()


@pytest.mark.parametrize(
    ("weekly_training_frequency", "expected_calories"),
    [(0, 1979), (1, 2267), (2, 2267), (3, 2556), (5, 2556), (6, 2844), (7, 2844)],
)
def test_target_suggestion_maps_legacy_training_frequency_to_activity_levels(
    weekly_training_frequency, expected_calories
):
    profile = UserProfile(
        height_cm=175,
        weight_kg=70,
        age=30,
        gender="male",
        goal="maintenance",
        weekly_training_frequency=weekly_training_frequency,
        target_weight_kg=70,
        daily_calorie_target=2000,
        daily_protein_target=120,
    )

    suggestion = suggest_targets(profile)

    assert suggestion.daily_calorie_target == expected_calories
    assert suggestion.daily_protein_target == 112


def test_target_suggestion_maps_legacy_other_gender_to_neutral_energy_parameter():
    profile = UserProfile(
        height_cm=175,
        weight_kg=70,
        age=30,
        gender="other",
        goal="maintenance",
        weekly_training_frequency=4,
        target_weight_kg=70,
        daily_calorie_target=2000,
        daily_protein_target=120,
    )

    suggestion = suggest_targets(profile)

    assert suggestion.daily_calorie_target == 2427


@pytest.mark.parametrize(
    ("age", "expected_calories"),
    [(16, 2492), (17, 2484)],
)
def test_target_suggestion_preserves_valid_legacy_under_18_profiles(
    age, expected_calories
):
    profile = UserProfile(
        height_cm=175,
        weight_kg=70,
        age=age,
        gender="male",
        goal="maintenance",
        weekly_training_frequency=4,
        target_weight_kg=70,
        daily_calorie_target=2000,
        daily_protein_target=120,
    )

    suggestion = suggest_targets(profile)

    assert suggestion.daily_calorie_target == expected_calories
    assert suggestion.daily_protein_target == 105


@pytest.mark.parametrize(
    ("profile_fields", "expected"),
    [
        (
            {
                "height_cm": 230,
                "weight_kg": 250,
                "age": 90,
                "gender": "male",
                "goal": "muscle_gain",
                "weekly_training_frequency": 7,
            },
            (5000, 300),
        ),
        (
            {
                "height_cm": 120,
                "weight_kg": 30.01,
                "age": 90,
                "gender": "female",
                "goal": "fat_loss",
                "weekly_training_frequency": 0,
            },
            (1200, 54),
        ),
    ],
)
def test_target_suggestion_preserves_legacy_output_at_profile_boundaries(
    profile_fields, expected
):
    profile = UserProfile(
        **profile_fields,
        target_weight_kg=70,
        daily_calorie_target=2000,
        daily_protein_target=120,
    )

    suggestion = suggest_targets(profile)

    assert (suggestion.daily_calorie_target, suggestion.daily_protein_target) == expected


@pytest.mark.parametrize(
    "error_code",
    ["TARGET_CALCULATION_RESTRICTED", "UNEXPECTED_TARGET_ERROR"],
)
def test_target_suggestion_does_not_fallback_for_unexpected_adult_domain_errors(
    monkeypatch, error_code
):
    profile = UserProfile(
        height_cm=175,
        weight_kg=70,
        age=30,
        gender="male",
        goal="maintenance",
        weekly_training_frequency=4,
        target_weight_kg=70,
        daily_calorie_target=2000,
        daily_protein_target=120,
    )

    def reject_target(*args, **kwargs):
        raise TargetDomainError(error_code)

    monkeypatch.setattr(target_suggestions, "calculate_daily_targets", reject_target)

    with pytest.raises(TargetDomainError) as raised:
        suggest_targets(profile)

    assert raised.value.code == error_code
