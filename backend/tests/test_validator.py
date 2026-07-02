from backend.agent.validator import validate_generated_plan


def test_validator_flags_low_calories_allergy_and_missing_rest_day():
    profile = {
        "weight_kg": 72,
        "daily_calorie_target": 2100,
        "daily_protein_target": 130,
        "allergies_or_restrictions": ["peanut"],
        "weekly_training_frequency": 4,
    }
    plan = {
        "diet_plan": {
            "daily_calorie_target": 1100,
            "daily_protein_target": 60,
            "meals": ["peanut butter oats"],
        },
        "workout_plan": {
            "weekly_training_days": 7,
            "days": [
                {"day": "Mon", "intensity": "high"},
                {"day": "Tue", "intensity": "high"},
                {"day": "Wed", "intensity": "high"},
            ],
            "rest_days": [],
        },
    }

    result = validate_generated_plan(plan, profile)

    assert result["passed"] is False
    assert any("热量" in item for item in result["violations"])
    assert any("peanut" in item for item in result["violations"])
    assert any("休息" in item for item in result["violations"])


def test_validator_accepts_reasonable_plan():
    profile = {
        "weight_kg": 72,
        "daily_calorie_target": 2100,
        "daily_protein_target": 130,
        "allergies_or_restrictions": ["peanut"],
        "weekly_training_frequency": 4,
    }
    plan = {
        "diet_plan": {
            "daily_calorie_target": 2100,
            "daily_protein_target": 130,
            "meals": ["oats", "beef rice", "salmon salad"],
        },
        "workout_plan": {
            "weekly_training_days": 4,
            "days": [
                {"day": "Mon", "intensity": "medium"},
                {"day": "Tue", "intensity": "rest"},
                {"day": "Wed", "intensity": "high"},
                {"day": "Fri", "intensity": "medium"},
            ],
            "rest_days": ["Tue", "Sun"],
        },
    }

    assert validate_generated_plan(plan, profile)["passed"] is True
