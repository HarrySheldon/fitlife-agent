from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.domain.profile_targets import TargetDomainError
from backend.schemas import (
    OverallGoalUpdateRequest,
    ProfileVersionUpdateRequest,
    TargetConfirmRequest,
    UserProfile,
)
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


def test_legacy_profile_accepts_pinned_sqlite_projection_boundaries():
    profile = UserProfile(
        height_cm=230,
        weight_kg=300,
        age=100,
        gender="other",
        goal="maintenance",
        weekly_training_frequency=0,
        target_weight_kg=300,
        daily_calorie_target=6000,
        daily_protein_target=400,
    )

    assert profile.height_cm == 230
    assert profile.weight_kg == 300
    assert profile.age == 100
    assert profile.daily_calorie_target == 6000
    assert profile.daily_protein_target == 400


def test_legacy_profile_retains_minimum_age_16():
    profile = UserProfile(
        height_cm=175,
        weight_kg=70,
        age=16,
        gender="male",
        goal="maintenance",
        weekly_training_frequency=0,
        target_weight_kg=70,
        daily_calorie_target=2000,
        daily_protein_target=100,
    )

    assert profile.age == 16


def test_legacy_profile_accepts_pinned_sqlite_projection_minimums():
    profile = UserProfile(
        height_cm=120,
        weight_kg=30,
        age=16,
        gender="female",
        goal="fat_loss",
        weekly_training_frequency=0,
        target_weight_kg=30,
        daily_calorie_target=800,
        daily_protein_target=20,
    )

    assert profile.weight_kg == 30
    assert profile.target_weight_kg == 30
    assert profile.daily_calorie_target == 800
    assert profile.daily_protein_target == 20


def _profile_version_request(effective_from):
    return ProfileVersionUpdateRequest(
        age=30,
        height_cm=175,
        weight_kg=70,
        energy_parameter="male",
        activity_level="moderate",
        effective_from=effective_from,
    )


def _goal_request(effective_from):
    return OverallGoalUpdateRequest(
        goal="maintenance",
        effective_from=effective_from,
    )


def _confirmation_request(effective_from):
    return TargetConfirmRequest(
        effective_from=effective_from,
        preview={
            "profile_version_id": "profile-1",
            "overall_goal_version_id": "goal-1",
            "targets": {
                "calories": 2200,
                "carbs": 280,
                "protein": 120,
                "fat": 67,
            },
            "source": "deterministic_calculation",
            "formula_version": "mifflin_st_jeor_v1",
            "preview_token": "0" * 64,
        },
    )


@pytest.mark.parametrize(
    "factory",
    [_profile_version_request, _goal_request, _confirmation_request],
)
def test_versioned_request_effective_from_requires_timezone(factory):
    with pytest.raises(ValidationError):
        factory("2026-07-22T08:00:00")


@pytest.mark.parametrize(
    "factory",
    [_profile_version_request, _goal_request, _confirmation_request],
)
def test_versioned_request_effective_from_rejects_invalid_datetime(factory):
    with pytest.raises(ValidationError):
        factory("not-a-datetime")


@pytest.mark.parametrize(
    "factory",
    [_profile_version_request, _goal_request, _confirmation_request],
)
def test_versioned_request_effective_from_normalizes_to_utc(factory):
    request = factory("2026-07-22T16:30:00+08:00")

    assert request.effective_from == datetime(
        2026, 7, 22, 8, 30, tzinfo=timezone.utc
    )
    assert request.model_dump(mode="json")["effective_from"] == (
        "2026-07-22T08:30:00Z"
    )


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
