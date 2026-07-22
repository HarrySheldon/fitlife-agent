from pydantic import BaseModel

from backend.domain.profile_targets import (
    ActivityLevel,
    ProfileInput,
    TargetDomainError,
    calculate_daily_targets,
)
from backend.schemas import UserProfile


class TargetSuggestion(BaseModel):
    daily_calorie_target: int
    daily_protein_target: int
    source: str = "system"
    rationale: str


def suggest_targets(profile: UserProfile) -> TargetSuggestion:
    try:
        targets = calculate_daily_targets(
            ProfileInput(
                age=profile.age,
                height_cm=profile.height_cm,
                weight_kg=profile.weight_kg,
                energy_parameter=(
                    profile.gender
                    if profile.gender in {"male", "female"}
                    else "neutral"
                ),
                activity_level=_activity_level(profile.weekly_training_frequency),
            ),
            profile.goal,
        )
        calories = max(1200, min(5000, targets.calories))
        protein = max(40, min(300, targets.protein))
    except TargetDomainError as error:
        can_use_legacy_fallback = error.code == "TARGET_OUT_OF_RANGE" or (
            error.code == "TARGET_CALCULATION_RESTRICTED" and profile.age < 18
        )
        if not can_use_legacy_fallback:
            raise
        calories, protein = _legacy_targets(profile)

    if profile.goal == "fat_loss":
        rationale = "Fat loss target uses a moderate deficit from estimated maintenance."
    elif profile.goal == "muscle_gain":
        rationale = "Muscle gain target uses a conservative surplus from estimated maintenance."
    else:
        rationale = "Maintenance target is based on estimated daily expenditure."

    return TargetSuggestion(
        daily_calorie_target=calories,
        daily_protein_target=protein,
        rationale=rationale,
    )


def _activity_level(weekly_training_frequency: int) -> ActivityLevel:
    if weekly_training_frequency == 0:
        return "sedentary"
    if weekly_training_frequency <= 2:
        return "light"
    if weekly_training_frequency <= 5:
        return "moderate"
    return "high"


def _legacy_targets(profile: UserProfile) -> tuple[int, int]:
    base = 10 * profile.weight_kg + 6.25 * profile.height_cm - 5 * profile.age
    if profile.gender == "male":
        base += 5
    elif profile.gender == "female":
        base -= 161

    activity_multiplier = 1.25 + min(profile.weekly_training_frequency, 6) * 0.05
    maintenance = int(base * activity_multiplier)
    if profile.goal == "fat_loss":
        calories = maintenance - 400
    elif profile.goal == "muscle_gain":
        calories = maintenance + 250
    else:
        calories = maintenance

    protein_multiplier = 1.8 if profile.goal in {"fat_loss", "muscle_gain"} else 1.5
    protein = int(round(profile.weight_kg * protein_multiplier))
    return (
        max(1200, min(5000, calories)),
        max(40, min(300, protein)),
    )
