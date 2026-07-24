from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query

from backend.api.dependencies import require_current_user
from backend.api.meal_schemas import CustomFoodRequest
from backend.api.utils import ok
from backend.application.use_cases.food_catalog import (
    CustomFoodCommand,
    FoodCatalogService,
)
from backend.config import get_settings
from backend.infrastructure.repositories.sqlite_food_catalog_repository import (
    SQLiteFoodCatalogRepository,
)
from backend.infrastructure.sqlite.runtime import get_database
from backend.infrastructure.user_lifecycle import user_lifecycle_guard
from backend.schemas import AuthenticatedUser


router = APIRouter(prefix="/api/v1/catalog/foods")


def get_food_catalog_service() -> FoodCatalogService:
    return FoodCatalogService(
        SQLiteFoodCatalogRepository(get_database()),
        mutation_scope=lambda user_id: user_lifecycle_guard(
            get_settings().data_dir,
            user_id,
        ),
    )


@router.get("/search")
def search_foods(
    q: str = Query(default="", max_length=256),
    limit: int = Query(default=20, ge=1, le=50),
    user: AuthenticatedUser = Depends(require_current_user),
    service: FoodCatalogService = Depends(get_food_catalog_service),
):
    results = service.search(user.user_id, q, limit=limit)
    return ok(
        [asdict(item) for item in results],
        processing_mode="deterministic",
    )


@router.post("/custom")
def create_custom_food(
    payload: CustomFoodRequest,
    user: AuthenticatedUser = Depends(require_current_user),
    service: FoodCatalogService = Depends(get_food_catalog_service),
):
    created = service.create_custom_food(
        user.user_id,
        CustomFoodCommand(
            name=payload.name,
            basis_type=payload.basis_type,
            basis_amount=payload.basis_amount,
            unit=payload.unit,
            calories=payload.calories,
            carbs=payload.carbs,
            protein=payload.protein,
            fat=payload.fat,
            aliases=tuple(payload.aliases),
        ),
    )
    return ok(asdict(created), processing_mode="deterministic")


@router.put("/{food_id}/favorite")
def add_favorite(
    food_id: str,
    user: AuthenticatedUser = Depends(require_current_user),
    service: FoodCatalogService = Depends(get_food_catalog_service),
):
    service.set_favorite(user.user_id, food_id, True)
    return ok({"favorite": True}, processing_mode="deterministic")


@router.delete("/{food_id}/favorite")
def remove_favorite(
    food_id: str,
    user: AuthenticatedUser = Depends(require_current_user),
    service: FoodCatalogService = Depends(get_food_catalog_service),
):
    service.set_favorite(user.user_id, food_id, False)
    return ok({"favorite": False}, processing_mode="deterministic")
