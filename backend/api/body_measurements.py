"""API routes for body measurements time-series (weight, body fat, circumferences)."""
from __future__ import annotations

from datetime import date as calendar_date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.api.dependencies import require_current_user
from backend.api.preference_context import preferences_for
from backend.api.profile_resolution import resolve_authoritative_profile_context
from backend.api.utils import ok
from backend.domain.account_clock import local_today
from backend.domain.body_measurements import compute_body_summary
from backend.domain.errors import ApplicationError
from backend.infrastructure.repositories.cutover_fitness_repository import get_fitness_repository
from backend.infrastructure.repositories.sqlite_body_measurement_repository import (
    SQLiteBodyMeasurementRepository,
)
from backend.infrastructure.sqlite.runtime import get_database
from backend.schemas import AuthenticatedUser

router = APIRouter(prefix="/api/v1/body-measurements")


class CreateBodyMeasurementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    measured_date: calendar_date | None = None
    weight_kg: float | None = Field(default=None, ge=25, le=350)
    body_fat_pct: float | None = Field(default=None, ge=2, le=70)
    waist_cm: float | None = Field(default=None, ge=30, le=250)
    chest_cm: float | None = Field(default=None, ge=40, le=250)
    hip_cm: float | None = Field(default=None, ge=40, le=250)
    note: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def require_at_least_one_metric(self) -> "CreateBodyMeasurementRequest":
        if (
            self.weight_kg is None
            and self.body_fat_pct is None
            and self.waist_cm is None
            and self.chest_cm is None
            and self.hip_cm is None
        ):
            raise ValueError("At least one measurement metric is required.")
        return self


def get_body_measurement_repo() -> SQLiteBodyMeasurementRepository:
    return SQLiteBodyMeasurementRepository(get_database())


@router.get("")
def list_body_measurements(
    days: int | None = Query(default=90, ge=7, le=3650),
    user: AuthenticatedUser = Depends(require_current_user),
    repo: SQLiteBodyMeasurementRepository = Depends(get_body_measurement_repo),
):
    prefs = preferences_for(user)
    today = local_today(prefs.timezone).isoformat()
    entries = repo.list_for_user(user.user_id, days=days, end_date=today)
    target_weight_kg = _target_weight_for(user.user_id)
    summary = compute_body_summary(entries, target_weight_kg=target_weight_kg)
    return ok(
        {
            "entries": [item.to_dict() for item in entries],
            "summary": summary.to_dict(),
        },
        processing_mode="deterministic",
    )


@router.post("", status_code=201)
def create_body_measurement(
    payload: CreateBodyMeasurementRequest,
    user: AuthenticatedUser = Depends(require_current_user),
    repo: SQLiteBodyMeasurementRepository = Depends(get_body_measurement_repo),
):
    prefs = preferences_for(user)
    measured_date = (payload.measured_date or local_today(prefs.timezone)).isoformat()
    created = repo.create(
        user.user_id,
        measured_date=measured_date,
        weight_kg=payload.weight_kg,
        body_fat_pct=payload.body_fat_pct,
        waist_cm=payload.waist_cm,
        chest_cm=payload.chest_cm,
        hip_cm=payload.hip_cm,
        note=payload.note,
    )
    entries = repo.list_for_user(user.user_id, days=90, end_date=local_today(prefs.timezone).isoformat())
    summary = compute_body_summary(entries, target_weight_kg=_target_weight_for(user.user_id))
    return ok(
        {
            "entry": created.to_dict(),
            "summary": summary.to_dict(),
        },
        processing_mode="deterministic",
    )


@router.delete("/{measurement_id}")
def delete_body_measurement(
    measurement_id: str,
    user: AuthenticatedUser = Depends(require_current_user),
    repo: SQLiteBodyMeasurementRepository = Depends(get_body_measurement_repo),
):
    deleted = repo.delete(user.user_id, measurement_id)
    if not deleted:
        raise ApplicationError(
            code="BODY_MEASUREMENT_NOT_FOUND",
            message="Body measurement record was not found.",
            status_code=404,
        )
    return ok({"deleted": True, "id": measurement_id}, processing_mode="deterministic")


def _target_weight_for(user_id: str) -> float | None:
    try:
        profile = get_fitness_repository().read_profile(user_id)
        return resolve_authoritative_profile_context(
            get_database(), user_id, profile
        ).target_weight_kg
    except Exception:
        return None
