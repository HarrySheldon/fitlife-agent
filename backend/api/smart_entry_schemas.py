from __future__ import annotations

from datetime import date
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    pass


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


class ConfirmedSmartEntryResponse(BaseModel):
    draft_id: str
    log_date: str
    meal_ids: list[str]
    training_session_id: str | None
    replayed: bool


class DeletedSmartEntryResponse(BaseModel):
    deleted: bool
