from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from backend.domain.meals import BasisType, FoodDefinition, FoodSource


class FoodCatalogRepositoryError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class FoodCatalogItem:
    id: str
    owner_user_id: str | None
    source: FoodSource
    source_name: str
    source_record_id: str
    dataset_version: str | None
    name: str
    basis_type: BasisType
    basis_amount: float
    unit: str
    calories: float
    carbs: float
    protein: float
    fat: float
    license: str | None
    attribution: str | None
    provenance: dict[str, object]
    content_hash: str | None
    active: bool
    aliases: tuple[str, ...]
    is_favorite: bool
    use_count: int
    last_used_at: str | None
    rank_group: int


@dataclass(frozen=True)
class NewCustomFood:
    definition: FoodDefinition
    aliases: tuple[str, ...] = ()


@runtime_checkable
class FoodCatalogRepository(Protocol):
    def search(
        self,
        user_id: str,
        query: str,
        *,
        limit: int,
    ) -> tuple[FoodCatalogItem, ...]: ...

    def create_custom_food(
        self,
        user_id: str,
        food: NewCustomFood,
    ) -> FoodCatalogItem: ...

    def set_favorite(
        self,
        user_id: str,
        food_id: str,
        favorite: bool,
    ) -> None: ...

    def record_usage(self, user_id: str, food_id: str) -> None: ...
