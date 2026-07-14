from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field, model_validator


T = TypeVar("T")
ProcessingMode = Literal["deterministic", "agent"]

ExperienceLevel = Literal["beginner", "novice", "experienced"]
TrainingPreference = Literal["strength", "cardio", "mixed"]
TargetMode = Literal["suggested", "manual"]
CoachSurface = Literal["today", "logbook", "review", "plan", "profile"]
CoachAction = Literal[
    "explain_today",
    "suggest_next_meal",
    "adjust_today_training",
    "explain_weekly_report",
    "adjust_next_plan",
    "suggest_targets",
]
ModelProvider = Literal["openai", "custom"]
ModelProtocol = Literal["responses", "chat_completions"]


class ApiError(BaseModel):
    code: str
    message: str


class ApiResponse(BaseModel, Generic[T]):
    success: bool
    data: T | None
    message: str = ""
    processing_mode: ProcessingMode | None = None
    error: ApiError | None = None


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
    experience_level: ExperienceLevel = "novice"
    training_preference: TrainingPreference = "mixed"
    target_mode: TargetMode = "suggested"


class AuthRegisterRequest(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=40)
    email: str | None = Field(default=None, min_length=3, max_length=254)
    phone: str | None = Field(default=None, min_length=6, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def require_identifier(self):
        if not (self.username or self.email or self.phone):
            raise ValueError("Username, email, or phone is required")
        return self


class AuthLoginRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class AuthenticatedUser(BaseModel):
    user_id: str
    username: str | None = None
    email: str | None = None
    phone: str | None = None
    display_name: str


class AuthSession(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: AuthenticatedUser


class ModelSettingsUpdateRequest(BaseModel):
    provider: ModelProvider
    protocol: ModelProtocol
    base_url: str | None = Field(default=None, max_length=2048)
    model: str = Field(min_length=1, max_length=200)
    enabled: bool
    api_key: str | None = Field(default=None, min_length=1, max_length=4096)


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


class DailySummary(BaseModel):
    date: str
    calories: float = 0
    protein: float = 0
    carbs: float = 0
    fat: float = 0
    meal_count: int = 0
    training_sessions: int = 0
    training_duration_min: float = 0
    has_data: bool = False


class DailyDetail(BaseModel):
    summary: DailySummary
    meals: list[MealRecord]
    workouts: list[WorkoutRecord]


class TargetProgress(BaseModel):
    label: str
    current: float
    target: float
    unit: str
    remaining: float
    status: Literal["under", "met", "over"]


class TodayOverview(BaseModel):
    date: str
    summary: DailySummary
    meals: list[MealRecord]
    workouts: list[WorkoutRecord]
    targets: list[TargetProgress]
    coach_actions: list[str]


class CoachActionRequest(BaseModel):
    surface: CoachSurface
    action: CoachAction
    date: str | None = None
    question: str | None = Field(default=None, max_length=1000)


class CoachActionResponse(BaseModel):
    surface: CoachSurface
    action: CoachAction
    answer_markdown: str
    intent: str
    trace: dict
    sources: list[dict] = Field(default_factory=list)
    model: str
    request_id: str


class AgentEntryRequest(BaseModel):
    date: str
    text: str = Field(min_length=1, max_length=1000)


class AgentEntryResponse(BaseModel):
    parsed_actions: list[str]
    day: DailyDetail


class DashboardSummary(BaseModel):
    summary_date: str
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
    sources: list[dict] = Field(default_factory=list)
    model: str
    request_id: str


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
