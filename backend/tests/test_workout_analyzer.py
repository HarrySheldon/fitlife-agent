import pandas as pd
import pytest

from backend.tools.workout_analyzer import analyze_workouts, validate_workout_columns


def sample_workouts() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": "2026-06-01",
                "type": "strength",
                "exercise": "squat",
                "muscle_group": "legs",
                "sets": 4,
                "reps": 8,
                "weight": 80,
                "duration_min": 55,
            },
            {
                "date": "2026-06-03",
                "type": "strength",
                "exercise": "bench press",
                "muscle_group": "chest",
                "sets": 4,
                "reps": 8,
                "weight": 60,
                "duration_min": 50,
            },
            {
                "date": "2026-06-08",
                "type": "cardio",
                "exercise": "run",
                "muscle_group": "full_body",
                "sets": None,
                "reps": None,
                "weight": None,
                "duration_min": 35,
            },
        ]
    )


def test_analyze_workouts_computes_frequency_duration_volume_and_gaps():
    result = analyze_workouts(sample_workouts())

    assert result["weekly_training_counts"]["2026-W23"] == 2
    assert result["weekly_training_counts"]["2026-W24"] == 1
    assert result["type_distribution"]["strength"] == 2
    assert result["weekly_duration_min"]["2026-W23"] == 105
    assert result["total_strength_volume"] == pytest.approx(4480)
    assert "back" in result["undertrained_muscle_groups"]
    assert result["week_over_week_volume_change"] < 0
    assert "训练" in result["summary"]


def test_validate_workout_columns_reports_missing_columns():
    frame = sample_workouts().drop(columns=["sets", "duration_min"])

    with pytest.raises(ValueError, match="sets, duration_min"):
        validate_workout_columns(frame)
