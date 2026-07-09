from pydantic import BaseModel

from backend.schemas import UserProfile


class TargetSuggestion(BaseModel):
    daily_calorie_target: int
    daily_protein_target: int
    source: str = "system"
    rationale: str


def suggest_targets(profile: UserProfile) -> TargetSuggestion:
    base = 10 * profile.weight_kg + 6.25 * profile.height_cm - 5 * profile.age
    if profile.gender == "male":
        base += 5
    elif profile.gender == "female":
        base -= 161
    activity_multiplier = 1.25 + min(profile.weekly_training_frequency, 6) * 0.05
    maintenance = int(base * activity_multiplier)

    if profile.goal == "fat_loss":
        calories = maintenance - 400
        rationale = "Fat loss target uses a moderate deficit from estimated maintenance."
    elif profile.goal == "muscle_gain":
        calories = maintenance + 250
        rationale = "Muscle gain target uses a conservative surplus from estimated maintenance."
    else:
        calories = maintenance
        rationale = "Maintenance target is based on estimated daily expenditure."

    protein_multiplier = 1.8 if profile.goal in {"fat_loss", "muscle_gain"} else 1.5
    protein = int(round(profile.weight_kg * protein_multiplier))

    return TargetSuggestion(
        daily_calorie_target=max(1200, min(5000, calories)),
        daily_protein_target=max(40, min(300, protein)),
        rationale=rationale,
    )
