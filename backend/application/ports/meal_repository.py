from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from backend.domain.meals import BasisType, FoodSource


MealType = Literal["breakfast", "lunch", "dinner", "snack", "custom"]


class MealRepositoryError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CustomFoodSnapshot:
    name: str
    basis_type: BasisType
    basis_amount: float
    unit: str
    calories: float
    carbs: float
    protein: float
    fat: float


@dataclass(frozen=True)
class MealDraftItemInput:
    amount: float
    unit: str
    catalog_food_id: str | None = None
    custom_food: CustomFoodSnapshot | None = None


@dataclass(frozen=True)
class MealDraftInput:
    log_date: str
    name: str
    meal_type: MealType
    entry_method: Literal["form"]
    items: tuple[MealDraftItemInput, ...]


@dataclass(frozen=True)
class MealItemSnapshot:
    catalog_food_id: str | None
    food_name: str
    amount: float
    unit: str
    basis_type: BasisType
    calories: float
    carbs: float
    protein: float
    fat: float
    source: FoodSource
    is_estimate: bool
    uncertainty: dict[str, object]
    assumptions: tuple[str, ...]
    provenance: dict[str, object]
    custom_food: CustomFoodSnapshot | None = None


@dataclass(frozen=True)
class MealDraftPayload:
    log_date: str
    name: str
    meal_type: MealType
    entry_method: Literal["form"]
    items: tuple[MealItemSnapshot, ...]


@dataclass(frozen=True)
class MealDraft:
    id: str
    user_id: str
    payload: MealDraftPayload
    version: int
    expires_at: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ConfirmedMeal:
    id: str
    user_id: str
    log_date: str
    name: str
    meal_type: MealType
    position: int
    entry_method: str
    items: tuple[MealItemSnapshot, ...]
    created_at: str
    updated_at: str
    replayed: bool = False


@runtime_checkable
class MealRepository(Protocol):
    def create_draft(
        self,
        user_id: str,
        payload: MealDraftInput,
        expires_at: str,
    ) -> MealDraft: ...

    def get_draft(self, user_id: str, draft_id: str) -> MealDraft | None: ...

    def update_draft(
        self,
        user_id: str,
        draft_id: str,
        *,
        expected_version: int,
        payload: MealDraftInput,
    ) -> MealDraft: ...

    def delete_draft(self, user_id: str, draft_id: str) -> None: ...

    def confirm(
        self,
        user_id: str,
        draft_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> ConfirmedMeal: ...

    def list_meals(
        self,
        user_id: str,
        log_date: str,
    ) -> tuple[ConfirmedMeal, ...]: ...
