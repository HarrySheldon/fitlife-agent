"""Stage-specific projections. Builders accept named fragments, never workflow state.

Allowlisted structures reduce disclosure; text cleaning is deliberately bounded,
not a claim to recognize every possible personal identifier.
"""
from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.domain.errors import ApplicationError


class InputClarificationRequired(ApplicationError):
    """A required restriction cannot safely be forwarded to a model."""

    def __init__(self, code="INPUT_CLARIFICATION_REQUIRED"):
        super().__init__(code=code, message="Please clarify the required input.",
                         status_code=422, processing_mode="agent")


TARGETS = {"calories": None, "protein": None, "carbs": None, "fat": None,
           "daily_calorie_target": None, "daily_protein_target": None}
FOOD = {"food": None, "name": None, "amount": None, "unit": None, "calories": None,
        "protein": None, "carbs": None, "fat": None, "meal": None, "date": None,
        "confidence": None, "source": None, "food_id": None}
EXERCISE = {"name": None, "exercise": None, "sets": None, "reps": None,
            "duration_min": None, "intensity": None, "rest_seconds": None}
TRAINING = {"summary": None, "weekly_training_days": None, "rest_days": None, "notes": None,
            "days": {"day": None, "type": None, "focus": None, "intensity": None,
                     "exercises": EXERCISE, "duration_min": None, "sets": None, "reps": None},
            "total_strength_volume": None, "undertrained_muscle_groups": None,
            "week_over_week_volume_change": None}
DIET = {"summary": None, **TARGETS, "meals": {**FOOD, "items": FOOD, "foods": FOOD}, "substitutions": None}
SOURCE = {"source": None, "heading": None, "text": None, "score": None, "id": None}
VALIDATION = {"valid": None, "passed": None, "issues": None, "warnings": None,
              "errors": None, "status": None, "violations": None, "repair_suggestions": None}
DATE_METRICS = {"__key_pattern__": r"\d{4}-\d{2}-\d{2}", "__value__": {"calories": None, "protein": None, "carbs": None, "fat": None}}
WEEK_NUMBERS = {"__key_pattern__": r"\d{4}-W\d{2}", "__value__": "number"}
MEAL_SUMMARY = {"summary": None, "weekly_average_calories": None, "weekly_average_protein": None,
                "highest_calorie_food": FOOD, "protein_target_met": None, "calorie_target_exceeded": None,
                "daily_totals": DATE_METRICS}
WORKOUT_SUMMARY = {"summary": None, "weekly_training_counts": WEEK_NUMBERS,
                   "weekly_duration_min": WEEK_NUMBERS,
                   "type_distribution": {"strength": None, "cardio": None, "flexibility": None, "other": None},
                   "total_strength_volume": None, "undertrained_muscle_groups": None,
                   "week_over_week_volume_change": None}
REPORT = {"title": None, "sections": {"title": None, "content": None}, "checklist": None}
PLAN = {"diet_plan": DIET, "workout_plan": TRAINING, "validation": VALIDATION}
TOOLS = {"meal_analysis": MEAL_SUMMARY, "workout_analysis": WORKOUT_SUMMARY,
         "weekly_report": REPORT, "generated_plan": PLAN, "active_plan": PLAN,
         "report_week": None, "active_plan_id": None}
PROFILE = {**TARGETS, "allergies_or_restrictions": None, "diet_preferences": None,
           "action_restrictions": None}


def project(value: Any, schema: dict | None) -> Any:
    """A leaf permits scalar values or scalar lists, never an arbitrary mapping."""
    if isinstance(value, Mapping):
        if isinstance(schema, dict) and "__key_pattern__" in schema:
            return {key: (item if type(item) in (int, float) else None) if schema["__value__"] == "number"
                    else project(item, schema["__value__"])
                    for key, item in value.items() if isinstance(key, str) and re.fullmatch(schema["__key_pattern__"], key)}
        if schema is None:
            return None
        return {key: project(value[key], child) for key, child in schema.items() if key in value}
    if isinstance(value, (tuple, list)):
        return [project(item, schema) for item in value if schema is not None or not isinstance(item, (Mapping, list, tuple))]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return None


def clean_text(text: str) -> str:
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "", text)
    text = re.sub(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)", "", text)
    text = re.sub(r"(?i)\b(?:my name is|name\s*:)\s*[A-Za-z][A-Za-z'-]*(?:[ ]+(?!(?:and|but|I|have|am)\b)[A-Z][A-Za-z'-]*)*[.!?;,]?[ ]*", "", text)
    text = re.sub(r"(?:我叫|我的名字是|姓名[：:])[^，。；！？\s]{1,4}?(?=对|有|患|需要|，|。|；|！|？|\s|$)[，。；]?[ ]*", "", text)
    return text.strip()


def _clean(value):
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    return value


class StageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def clean_fields(cls, data):
        data = dict(data) if isinstance(data, Mapping) else data
        if isinstance(data, dict):
            if cls.__name__ == "CoordinatorInput":
                for domain, key in (("training", "training_patch"), ("diet", "diet_patch")):
                    if key in data:
                        data[key] = project_patch(data[key], domain=domain)
            for key, schema in _SCHEMAS.get(cls.__name__, {}).items():
                if key in data:
                    data[key] = project(data[key], schema)
        cleaned = _clean(data)
        if isinstance(data, dict):
            pairs = [(data, cleaned)]
            if isinstance(data.get("profile"), dict):
                pairs.append((data["profile"], cleaned["profile"]))
            for original, result in pairs:
                for key in ("allergies", "avoidances", "action_restrictions", "constraints", "conflicts", "allergies_or_restrictions"):
                    if original.get(key) and any(not str(item).strip() for item in result.get(key, ())):
                        raise InputClarificationRequired("INPUT_CONSTRAINT_CLARIFICATION_REQUIRED")
            for key in ("current_meal_text", "question", "user_query", "draft", "adjustment_instructions"):
                if data.get(key) and not cleaned.get(key):
                    raise InputClarificationRequired("INPUT_CLARIFICATION_REQUIRED")
        return cleaned


class EntryInput(StageInput):
    current_meal_text: str
    confirmed_items: list[dict] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    catalog_matches: list[dict] = Field(default_factory=list)
    estimation_provenance: list[str] = Field(default_factory=list)
    unresolved_workout: str = ""
    locale: str = ""
    candidates: list["EntryCandidateDTO"] = Field(default_factory=list)


class EntryCandidateDTO(StageInput):
    id: str = Field(min_length=1, max_length=100)
    kind: str
    source_segment: str
    issues: list[str] = Field(default_factory=list)
    explicit_values: dict = Field(default_factory=dict)


class PlanAdjustmentInput(StageInput):
    """Bounded compatibility input, not a consent or patch execution engine."""
    adjustment_instructions: str
    training_fragment: dict = Field(default_factory=dict)
    diet_fragment: dict = Field(default_factory=dict)


class TrainingInput(StageInput):
    training_fragment: dict
    time: str | int
    equipment: list[str]
    goals: list[str]
    experience: str
    execution_summary: dict
    action_restrictions: list[str]


class DietInput(StageInput):
    diet_fragment: dict
    computed_nutrient_targets: dict
    allergies: list[str]
    avoidances: list[str]
    budget: str | int | float
    prep_time: str | int


class CoordinatorInput(StageInput):
    authorized_scope: list[str]
    training_patch: dict
    diet_patch: dict
    constraints: list[str]
    conflicts: list[str]


class FieldPatch(BaseModel):
    """One proposed edit, not permission to execute or persist it."""
    model_config = ConfigDict(extra="forbid")
    path: str
    old_value: Any
    new_value: Any
    reason: str
    evidence_refs: list[str]


def project_patch(value, *, domain):
    """Validate structural paths only; the future owner checks actual plan bounds.

    This pure projection neither resolves an index against a stored plan nor
    provides an atomic comparison or write.
    """
    if value == {}:
        return {}
    patch = FieldPatch.model_validate(value)
    parts = patch.path.split(".")
    root, schema = ("workout_plan", TRAINING) if domain == "training" else ("diet_plan", DIET)
    if len(parts) < 2 or parts[0] != root:
        raise ValueError("PATCH_PATH_NOT_ALLOWED")
    list_fields = {"days", "exercises", "meals", "items", "foods", "substitutions", "rest_days", "notes"}
    needs_index = False
    for part in parts[1:]:
        if needs_index:
            if not re.fullmatch(r"0|[1-9][0-9]*", part):
                raise ValueError("PATCH_PATH_NOT_ALLOWED")
            needs_index = False
            continue
        if not isinstance(schema, dict) or part not in schema:
            raise ValueError("PATCH_PATH_NOT_ALLOWED")
        schema = schema[part]
        needs_index = part in list_fields
    result = patch.model_dump()
    for key in ("old_value", "new_value"):
        if needs_index and not isinstance(result[key], list):
            raise ValueError("PATCH_VALUE_NOT_ALLOWED")
        if schema is None and isinstance(result[key], Mapping):
            raise ValueError("PATCH_VALUE_NOT_ALLOWED")
        result[key] = project(result[key], schema)
    return result


class ReviewInput(StageInput):
    question: str
    draft: str
    evidence: list[dict] = Field(default_factory=list)


class HistoryMessage(StageInput):
    role: Literal["user", "coach"]
    body: str = Field(max_length=4000)


class ChatInput(StageInput):
    user_query: str
    intent: str
    context_metadata: dict
    profile: dict
    tool_results: dict
    retrieved_docs: list[dict]
    validation_result: dict
    # Controlled metadata, not a hint. The writer instructions treat this as the
    # authoritative answer language; `context_metadata.language` is only the UI locale.
    answer_language: str = "en-US"
    answer_mode: str = "brief"
    recent_history: list[HistoryMessage] = Field(default_factory=list, max_length=12)


_SCHEMAS = {
    "EntryInput": {"confirmed_items": FOOD, "catalog_matches": FOOD},
    "EntryCandidateDTO": {"explicit_values": {"amount": None, "unit": None,
        "set_count": None, "reps": None, "load_kg": None, "duration_min": None,
        "device_calories": None}},
    "PlanAdjustmentInput": {"training_fragment": TRAINING, "diet_fragment": DIET},
    "TrainingInput": {"training_fragment": TRAINING, "execution_summary": WORKOUT_SUMMARY},
    "DietInput": {"diet_fragment": DIET, "computed_nutrient_targets": TARGETS},
    "ReviewInput": {"evidence": SOURCE},
    "ChatInput": {"context_metadata": {"language": None}, "answer_language": None,
                  "answer_mode": None, "profile": PROFILE,
                  "tool_results": TOOLS, "retrieved_docs": SOURCE, "validation_result": VALIDATION},
}


def structured_stage_input(operation: str, input_text: str) -> StageInput:
    """Choose a stage from the trusted caller operation, never payload fields."""
    import json
    try:
        data = json.loads(input_text)
    except (ValueError, TypeError):
        data = input_text
    if operation == "smart_entry":
        if isinstance(data, str):
            value = EntryInput(current_meal_text=data)
        elif isinstance(data, dict):
            allowed = set(EntryInput.model_fields)
            value = EntryInput.model_validate({key: item for key, item in data.items() if key in allowed})
        else:
            raise InputClarificationRequired()
    elif operation == "plan_adjustment":
        if not isinstance(data, dict):
            raise InputClarificationRequired()
        required_instructions = data.get("adjustment_instructions")
        if not isinstance(required_instructions, str) or not required_instructions.strip():
            raise InputClarificationRequired()
        plan = data.get("active_plan", {})
        plan = plan if isinstance(plan, dict) else {}
        value = PlanAdjustmentInput(
            adjustment_instructions=data.get("adjustment_instructions", ""),
            training_fragment=data.get("training_fragment", plan.get("workout_plan", {})),
            diet_fragment=data.get("diet_fragment", plan.get("diet_plan", {})))
    else:
        raise InputClarificationRequired()
    return sanitize_stage_input(value)


def validate_context_findings(report, *, reviewing_draft=False, stage=None) -> None:
    """Do not convert an unreadable safety constraint into an absent constraint."""
    critical = ("allergies", "avoidances", "action_restrictions", "constraints", "conflicts",
                "profile.allergies_or_restrictions", "profile.action_restrictions")
    if stage == "PlanAdjustmentInput":
        critical += ("adjustment_instructions", "training_fragment", "diet_fragment")
    if stage == "EntryInput":
        critical += ("current_meal_text", "unresolved_workout")
    if any(f.path.startswith(critical) or (reviewing_draft and f.path == "draft")
           or (stage == "EntryInput" and re.fullmatch(r"candidates\[\d+\]\.source_segment", f.path))
           for f in report.findings):
        raise InputClarificationRequired("INPUT_CONSTRAINT_CLARIFICATION_REQUIRED")


def sanitize_stage_input(value: StageInput) -> StageInput:
    from backend.safety.context import sanitize_context
    from backend.safety.gate import default_pack
    cleaned, report = sanitize_context(value.model_dump(), default_pack(), scan_all=True)
    validate_context_findings(report, reviewing_draft=isinstance(value, ReviewInput), stage=type(value).__name__)
    return type(value).model_validate(cleaned)


def build_entry_input(*, current_meal_text, confirmed_items=(), missing_fields=(),
                      catalog_matches=(), estimation_provenance=(), unresolved_workout="") -> EntryInput:
    return sanitize_stage_input(EntryInput(current_meal_text=current_meal_text, confirmed_items=project(confirmed_items, FOOD),
                      missing_fields=missing_fields, catalog_matches=project(catalog_matches, FOOD),
                      estimation_provenance=estimation_provenance, unresolved_workout=unresolved_workout))


def build_training_input(*, training_fragment, time, equipment, goals, experience,
                         execution_summary, action_restrictions) -> TrainingInput:
    return sanitize_stage_input(TrainingInput(training_fragment=project(training_fragment, TRAINING), time=time, equipment=equipment,
                         goals=goals, experience=experience, execution_summary=project(execution_summary, WORKOUT_SUMMARY),
                         action_restrictions=action_restrictions))


def build_diet_input(*, diet_fragment, computed_nutrient_targets, allergies, avoidances, budget, prep_time) -> DietInput:
    return sanitize_stage_input(DietInput(diet_fragment=project(diet_fragment, DIET), computed_nutrient_targets=project(computed_nutrient_targets, TARGETS),
                     allergies=allergies, avoidances=avoidances, budget=budget, prep_time=prep_time))


def build_coordinator_input(*, authorized_scope, training_patch, diet_patch, constraints, conflicts) -> CoordinatorInput:
    return sanitize_stage_input(CoordinatorInput(authorized_scope=authorized_scope, training_patch=project_patch(training_patch, domain="training"),
                            diet_patch=project_patch(diet_patch, domain="diet"), constraints=constraints, conflicts=conflicts))


def build_review_input(*, question, draft, evidence=()) -> ReviewInput:
    return sanitize_stage_input(ReviewInput(question=question, draft=draft, evidence=project(evidence, SOURCE)))


def build_chat_input(*, current_question, approved_intent, context_metadata, nutrient_targets_and_restrictions,
                     analysis_summaries, sources, validation, sanitize=True,
                     answer_language="en-US", answer_mode="brief", recent_history=()) -> ChatInput:
    selected = dict(TOOLS)
    if approved_intent == "meal_analysis":
        selected = {"meal_analysis": MEAL_SUMMARY}
    elif approved_intent == "workout_analysis":
        selected = {"workout_analysis": WORKOUT_SUMMARY}
    elif approved_intent == "knowledge_qa":
        selected = {}
    profile_schema = PROFILE
    if approved_intent in {"knowledge_qa", "workout_analysis"}:
        profile_schema = {"allergies_or_restrictions": None, "action_restrictions": None}
    result = ChatInput(user_query=current_question, intent=approved_intent,
        context_metadata=project(context_metadata, {"language": None}),
        profile=project(nutrient_targets_and_restrictions, profile_schema), tool_results=project(analysis_summaries, selected),
        retrieved_docs=project(sources, SOURCE), validation_result=project(validation, VALIDATION),
        answer_language=answer_language, answer_mode=answer_mode, recent_history=list(recent_history))
    return sanitize_stage_input(result) if sanitize else result
