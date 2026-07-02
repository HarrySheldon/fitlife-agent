import pandas as pd
import pytest

from backend.tools.meal_analyzer import analyze_meals, validate_meal_columns


def sample_meals() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": "2026-06-01",
                "meal": "breakfast",
                "food": "oats",
                "amount": "80g",
                "calories": 320,
                "protein": 12,
                "carbs": 52,
                "fat": 6,
            },
            {
                "date": "2026-06-01",
                "meal": "lunch",
                "food": "chicken rice",
                "amount": "1 bowl",
                "calories": 650,
                "protein": 45,
                "carbs": 72,
                "fat": 14,
            },
            {
                "date": "2026-06-02",
                "meal": "dinner",
                "food": "salmon pasta",
                "amount": "1 plate",
                "calories": 780,
                "protein": 38,
                "carbs": 86,
                "fat": 28,
            },
        ]
    )


def test_analyze_meals_computes_daily_totals_and_target_checks():
    result = analyze_meals(sample_meals(), calorie_target=1800, protein_target=70)

    assert result["daily_totals"]["2026-06-01"]["calories"] == 970
    assert result["daily_totals"]["2026-06-01"]["protein"] == 57
    assert result["weekly_average_calories"] == pytest.approx(875)
    assert result["weekly_average_protein"] == pytest.approx(47.5)
    assert result["highest_calorie_food"]["food"] == "salmon pasta"
    assert result["protein_target_met"] is False
    assert result["calorie_target_exceeded"] is False
    assert "蛋白质" in result["summary"]


def test_validate_meal_columns_reports_missing_columns():
    frame = sample_meals().drop(columns=["protein", "fat"])

    with pytest.raises(ValueError, match="protein, fat"):
        validate_meal_columns(frame)
