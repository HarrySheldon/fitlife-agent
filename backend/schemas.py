from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    success: bool
    data: T | None
    message: str = ""


class UserProfile(BaseModel):
    height_cm: int = Field(ge=120, le=230)
    weight_kg: float = Field(gt=30, le=250)
    age: int = Field(ge=16, le=90)
    gender: Literal["male", "female", "other"]
    goal: Literal["fat_loss", "muscle_gain", "maintenance"]
    weekly_training_frequency: int = Field(ge=0, le=7)
    diet_preferences: list[str] = Field(default_factory=list)
    allergies_or_restrictions: list[str] = Field(default_factory=list)
    target_weight_kg: float = Field(gt=30, le=250)
    daily_calorie_target: int = Field(ge=1200, le=5000)
    daily_protein_target: int = Field(ge=40, le=300)


class MealRecord(BaseModel):
    date: str
    meal: str
    food: str
    amount: str
    calories: float = Field(ge=0)
    protein: float = Field(ge=0)
    carbs: float = Field(ge=0)
    fat: float = Field(ge=0)


class WorkoutRecord(BaseModel):
    date: str
    type: str
    exercise: str
    muscle_group: str
    sets: float | None = Field(default=0, ge=0)
    reps: float | None = Field(default=0, ge=0)
    weight: float | None = Field(default=0, ge=0)
    duration_min: float = Field(ge=0)


class DashboardSummary(BaseModel):
    today_calories: float
    today_protein: float
    weekly_training_count: int
    weekly_training_duration_min: float
    calorie_trend: list[dict]
    protein_trend: list[dict]
    workout_count_trend: list[dict]
    macro_distribution: list[dict]


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)


class ChatResponse(BaseModel):
    answer_markdown: str
    intent: str
    trace: dict


class WeeklyReport(BaseModel):
    title: str
    sections: list[dict]
    checklist: list[str]
    trace: dict = Field(default_factory=dict)


class ValidationResult(BaseModel):
    passed: bool
    warnings: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)
    repair_suggestions: list[str] = Field(default_factory=list)


class GeneratedPlan(BaseModel):
    diet_plan: dict
    workout_plan: dict
    validation: ValidationResult
    trace: dict = Field(default_factory=dict)


class EvalCase(BaseModel):
    question: str
    expected_tool: str | None = None
    expected_retrieval_doc: str | None = None
    expected_answer_format: str = "markdown"
    expected_keywords: list[str] = Field(default_factory=list)


class EvalRunRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=100)


class EvalResult(BaseModel):
    total_tests: int
    pass_rate: float
    tool_call_success_rate: float
    retrieval_hit_rate: float
    structured_output_success_rate: float
    preference_compliance_rate: float
    validator_pass_rate: float
    failed_cases: list[dict]
    cases: list[dict]
