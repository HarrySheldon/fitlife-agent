from __future__ import annotations

from datetime import date
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from backend.domain.entry_interaction import EntryInteraction


class SmartEntryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    log_date: date
    raw_text: str = Field(min_length=1, max_length=10_000)


class CatalogChoiceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=50)
    aliases: list[str] = Field(default_factory=list, max_length=50)


class SmartCandidateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    kind: Literal["food", "strength", "cardio", "unknown"]
    raw_text: str = Field(min_length=1, max_length=2_000)
    normalized_text: str = Field(min_length=1, max_length=2_000)
    subject_text: str = Field(max_length=500)
    meal_context: Literal[
        "breakfast",
        "lunch",
        "dinner",
        "snack",
        "other",
    ] | None = None
    selected: bool = True
    selected_catalog_id: str | None = Field(default=None, max_length=200)
    catalog_choices: list[CatalogChoiceModel] = Field(
        default_factory=list,
        max_length=50,
    )
    issues: list[str] = Field(default_factory=list, max_length=20)
    values: dict[str, Any]
    provenance: dict[str, Any]
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    agent_estimate_accepted: bool = False

    @field_validator("values", "provenance")
    @classmethod
    def bound_json_object(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, ensure_ascii=False)) > 64 * 1024:
            raise ValueError("candidate object is too large")
        return value


class SmartEntryDraftMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    log_date: date
    raw_text: str = Field(min_length=1, max_length=10_000)
    parser_version: str = Field(min_length=1, max_length=100)
    candidates: list[SmartCandidateModel] = Field(
        min_length=1,
        max_length=100,
    )


class SmartEntryDraftPayloadResponse(SmartEntryDraftMutationRequest):
    interaction: EntryInteraction


class EntryItemCommitResponse(BaseModel):
    item_id: str
    item_revision: int
    meal_id: str
    meal_item_id: str
    record_state: Literal['unchanged', 'changed', 'deleted']


class DependencyValidityResponse(BaseModel):
    item_id: str
    catalog_id: str
    valid: bool


class InteractionStartRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: StrictInt = Field(ge=1)


class InteractionAnswerValue(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    item_id: str = Field(min_length=1, max_length=100)
    field: Literal['name', 'selected_catalog_id', 'amount', 'unit', 'intake_ratio',
                   'calories', 'carbs', 'protein', 'fat', 'basis_type']
    value: str | float | None


class InteractionAnswersRequest(InteractionStartRequest):
    question_group_id: str = Field(min_length=1, max_length=100)
    answers: list[InteractionAnswerValue] = Field(max_length=100)


class InteractionUpdates(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str | None = None
    selected_catalog_id: str | None = None
    amount: float | None = None
    unit: str | None = None
    intake_ratio: float | None = None
    calories: float | None = None
    carbs: float | None = None
    protein: float | None = None
    fat: float | None = None
    basis_type: Literal['per_100g', 'per_100ml', 'per_serving'] | None = None


class InteractionCorrectionRequest(InteractionStartRequest):
    item_id: str = Field(min_length=1, max_length=100)
    item_revision: StrictInt = Field(ge=1)
    updates: InteractionUpdates


class InteractionSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    item_id: str = Field(min_length=1, max_length=100)
    item_revision: StrictInt = Field(ge=1)


class InteractionConfirmRequest(InteractionStartRequest):
    selections: list[InteractionSelection] = Field(min_length=1, max_length=100)
    accepted_estimates: list[InteractionSelection] = Field(default_factory=list, max_length=100)


class ConfirmedEntryItemsResponse(BaseModel):
    draft_id: str
    commits: list[EntryItemCommitResponse]
    remaining_draft_version: int
    replayed: bool


class InteractiveCapabilitiesResponse(BaseModel):
    interactive_entry_enabled: bool
    entry_task_ttl_days: int


class SmartEntryDraftResponse(BaseModel):
    id: str
    user_id: str
    payload: SmartEntryDraftPayloadResponse
    version: int
    agent_status: Literal[
        "not_requested",
        "running",
        "completed",
        "failed",
    ]
    agent_prompt_version: str | None
    agent_model: str | None
    agent_metadata: dict[str, Any]
    expires_at: str
    created_at: str
    updated_at: str
    item_commits: list[EntryItemCommitResponse] = Field(default_factory=list)
    dependency_validity: list[DependencyValidityResponse] = Field(default_factory=list)


class ConfirmedSmartEntryResponse(BaseModel):
    draft_id: str
    log_date: str
    meal_ids: list[str]
    training_session_id: str | None
    replayed: bool


class DeletedSmartEntryResponse(BaseModel):
    deleted: bool
