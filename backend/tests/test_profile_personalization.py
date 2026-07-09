from backend.schemas import UserProfile
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

    assert 1600 <= suggestion.daily_calorie_target <= 2800
    assert 130 <= suggestion.daily_protein_target <= 180
    assert suggestion.source == "system"
    assert "fat loss" in suggestion.rationale.lower()
