from __future__ import annotations

from dataclasses import asdict
import re
from uuid import UUID

from fastapi import APIRouter, Depends, Header

from backend.api.dependencies import require_current_user
from backend.api.meal_schemas import (
    DraftCustomFoodRequest,
    MealDraftItemRequest,
    MealDraftMutationRequest,
)
from backend.api.utils import ok
from backend.application.ports.meal_repository import (
    CustomFoodSnapshot,
    MealDraftInput,
    MealDraftItemInput,
)
from backend.application.use_cases.meals import MealService, MealServiceError
from backend.config import get_settings
from backend.infrastructure.repositories.sqlite_meal_repository import (
    SQLiteMealRepository,
)
from backend.infrastructure.sqlite.runtime import get_database
from backend.infrastructure.user_lifecycle import user_lifecycle_guard
from backend.schemas import AuthenticatedUser


router = APIRouter(prefix="/api/v1/meal-drafts")


def get_meal_service() -> MealService:
    return MealService(
        SQLiteMealRepository(get_database()),
        mutation_scope=lambda user_id: user_lifecycle_guard(
            get_settings().data_dir,
            user_id,
        ),
    )


@router.post("")
def create_draft(
    payload: MealDraftMutationRequest,
    user: AuthenticatedUser = Depends(require_current_user),
    service: MealService = Depends(get_meal_service),
):
    created = service.create_draft(user.user_id, _draft_input(payload))
    return ok(asdict(created), processing_mode="deterministic")


@router.get("/{draft_id}")
def get_draft(
    draft_id: str,
    user: AuthenticatedUser = Depends(require_current_user),
    service: MealService = Depends(get_meal_service),
):
    draft = service.get_draft(user.user_id, draft_id)
    if draft is None:
        raise MealServiceError("DRAFT_NOT_FOUND", status_code=404)
    return ok(asdict(draft), processing_mode="deterministic")


@router.patch("/{draft_id}")
def update_draft(
    draft_id: str,
    payload: MealDraftMutationRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    user: AuthenticatedUser = Depends(require_current_user),
    service: MealService = Depends(get_meal_service),
):
    updated = service.update_draft(
        user.user_id,
        draft_id,
        expected_version=_draft_version(if_match),
        payload=_draft_input(payload),
    )
    return ok(asdict(updated), processing_mode="deterministic")


@router.delete("/{draft_id}")
def delete_draft(
    draft_id: str,
    user: AuthenticatedUser = Depends(require_current_user),
    service: MealService = Depends(get_meal_service),
):
    service.delete_draft(user.user_id, draft_id)
    return ok({"deleted": True}, processing_mode="deterministic")


@router.post("/{draft_id}/confirm")
def confirm_draft(
    draft_id: str,
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    user: AuthenticatedUser = Depends(require_current_user),
    service: MealService = Depends(get_meal_service),
):
    confirmed = service.confirm_draft(
        user.user_id,
        draft_id,
        expected_version=_draft_version(if_match),
        idempotency_key=_idempotency_key(idempotency_key),
    )
    return ok(asdict(confirmed), processing_mode="deterministic")


def _draft_input(payload: MealDraftMutationRequest) -> MealDraftInput:
    return MealDraftInput(
        log_date=payload.log_date.isoformat(),
        name=payload.name,
        meal_type=payload.meal_type,
        entry_method="form",
        items=tuple(_draft_item(item) for item in payload.items),
    )


def _draft_item(item: MealDraftItemRequest) -> MealDraftItemInput:
    return MealDraftItemInput(
        amount=item.amount,
        unit=item.unit,
        catalog_food_id=item.catalog_food_id,
        custom_food=(
            _custom_food(item.custom_food)
            if item.custom_food is not None
            else None
        ),
    )


def _custom_food(food: DraftCustomFoodRequest) -> CustomFoodSnapshot:
    return CustomFoodSnapshot(
        name=food.name,
        basis_type=food.basis_type,
        basis_amount=food.basis_amount,
        unit=food.unit,
        calories=food.calories,
        carbs=food.carbs,
        protein=food.protein,
        fat=food.fat,
    )


def _draft_version(value: str | None) -> int:
    if value is None:
        raise MealServiceError("DRAFT_VERSION_REQUIRED", status_code=422)
    token = value.strip()
    if (
        re.fullmatch(r'(?:[1-9]\d{0,18}|"[1-9]\d{0,18}")', token)
        is None
    ):
        raise MealServiceError("DRAFT_VERSION_INVALID", status_code=422) from None
    version = int(token.strip('"'))
    if version > 9_223_372_036_854_775_807:
        raise MealServiceError("DRAFT_VERSION_INVALID", status_code=422)
    return version


def _idempotency_key(value: str | None) -> str:
    if value is None:
        raise MealServiceError("IDEMPOTENCY_KEY_REQUIRED", status_code=422)
    try:
        return str(UUID(value))
    except (AttributeError, ValueError):
        raise MealServiceError("INVALID_IDEMPOTENCY_KEY", status_code=422) from None
