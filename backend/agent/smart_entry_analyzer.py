from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.application.ports.structured_model_gateway import (
    StructuredModelGateway,
    StructuredModelResult,
)
from backend.domain.smart_entry import ResolvedCandidate
from backend.agent.structured_workflow import run_structured_agent


PROMPT_VERSION = "smart-entry-analysis-v1"

SMART_ENTRY_ANALYSIS_INSTRUCTIONS = """
You analyze only unresolved meal and exercise candidate metadata.
Return the strict response schema. Never report completed sets, repetitions,
load, bodyweight, duration, or device calories. Those are observed user data.
Do not create formal records. Food values must describe the full assumed
serving represented by the source segment and include bounded ranges,
basis, serving assumption, and assumptions. Exercise suggestions may include
canonical name, type, muscles, and an optional MET estimate only.
""".strip()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NumericEstimate(StrictModel):
    value: float = Field(ge=0)
    min_value: float = Field(ge=0)
    max_value: float = Field(ge=0)
    basis: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def validate_range(self) -> "NumericEstimate":
        if not self.min_value <= self.value <= self.max_value:
            raise ValueError("estimate value must be inside its range")
        return self


class FoodAnalysisSuggestion(StrictModel):
    candidate_id: str = Field(min_length=1, max_length=100)
    canonical_name: str = Field(min_length=1, max_length=100)
    calories: NumericEstimate
    carbs: NumericEstimate
    protein: NumericEstimate
    fat: NumericEstimate
    serving_assumption: str = Field(min_length=1, max_length=300)
    assumptions: tuple[str, ...] = Field(max_length=20)


class ExerciseAnalysisSuggestion(StrictModel):
    candidate_id: str = Field(min_length=1, max_length=100)
    canonical_name: str = Field(min_length=1, max_length=100)
    exercise_type: Literal["strength", "cardio"]
    primary_muscle: str = Field(min_length=1, max_length=60)
    secondary_muscles: tuple[str, ...] = Field(max_length=20)
    met: NumericEstimate | None = None
    assumptions: tuple[str, ...] = Field(max_length=20)


class SmartEntryAnalysisResponse(StrictModel):
    food_suggestions: tuple[FoodAnalysisSuggestion, ...] = Field(
        default=(),
        max_length=100,
    )
    exercise_suggestions: tuple[ExerciseAnalysisSuggestion, ...] = Field(
        default=(),
        max_length=100,
    )


def analyze_smart_entry(
    gateway: StructuredModelGateway,
    candidates: tuple[ResolvedCandidate, ...],
    *,
    locale: str,
    weight_kg: float | None,
    user_id: str | None = None,
    request_id: str | None = None,
    gateway_resolver=None,
) -> StructuredModelResult:
    unresolved = tuple(candidate for candidate in candidates if candidate.issues)
    payload = {
        "locale": locale,
        "profile": {"weight_kg": weight_kg},
        "candidates": [
            {
                "id": candidate.id,
                "kind": candidate.kind,
                "source_segment": candidate.raw_text,
                "issues": candidate.issues,
                "explicit_values": {
                    key: candidate.values.get(key)
                    for key in (
                        "amount",
                        "unit",
                        "set_count",
                        "reps",
                        "load_kg",
                        "bodyweight",
                        "duration_min",
                        "device_calories",
                    )
                    if candidate.values.get(key) is not None
                },
            }
            for candidate in unresolved
        ],
    }
    return run_structured_agent(
        operation="smart_entry",
        question="\n".join(candidate.raw_text for candidate in unresolved),
        user_id=user_id, request_id=request_id,
        gateway_resolver=gateway_resolver or (lambda: gateway),
        instructions=SMART_ENTRY_ANALYSIS_INSTRUCTIONS,
        input_text=json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        response_model=SmartEntryAnalysisResponse,
    )
