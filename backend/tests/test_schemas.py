import pytest
from pydantic import ValidationError

from backend.schemas import (
    ApiResponse,
    ChatRequest,
    EvalCase,
    MealRecord,
    UserProfile,
    WorkoutRecord,
)


def test_user_profile_accepts_valid_demo_profile():
    profile = UserProfile(
        height_cm=175,
        weight_kg=72,
        age=24,
        gender="male",
        goal="fat_loss",
        weekly_training_frequency=4,
        diet_preferences=["high_protein"],
        allergies_or_restrictions=["peanut"],
        target_weight_kg=68,
        daily_calorie_target=2100,
        daily_protein_target=130,
    )

    assert profile.goal == "fat_loss"
    assert profile.daily_protein_target == 130


def test_user_profile_rejects_invalid_goal_and_impossible_values():
    with pytest.raises(ValidationError):
        UserProfile(
            height_cm=40,
            weight_kg=-1,
            age=5,
            gender="male",
            goal="bulk_forever",
            weekly_training_frequency=12,
            diet_preferences=[],
            allergies_or_restrictions=[],
            target_weight_kg=68,
            daily_calorie_target=600,
            daily_protein_target=0,
        )


def test_meal_and_workout_records_validate_numeric_fields():
    meal = MealRecord(
        date="2026-06-01",
        meal="breakfast",
        food="oats",
        amount="80g",
        calories=320,
        protein=12,
        carbs=52,
        fat=6,
    )
    workout = WorkoutRecord(
        date="2026-06-01",
        type="strength",
        exercise="squat",
        muscle_group="legs",
        sets=4,
        reps=8,
        weight=80,
        duration_min=50,
    )

    assert meal.carbs == 52
    assert workout.sets * workout.reps * workout.weight == 2560


def test_api_response_and_eval_case_contracts():
    response = ApiResponse[dict](success=True, data={"ok": True}, message="")
    case = EvalCase(
        question="我这周蛋白质吃够了吗？",
        expected_tool="analyze_meals",
        expected_retrieval_doc=None,
        expected_answer_format="markdown",
        expected_keywords=["蛋白质"],
    )
    chat = ChatRequest(question="帮我总结这周饮食问题。")

    assert response.data["ok"] is True
    assert case.expected_tool == "analyze_meals"
    assert chat.question.startswith("帮我")
