from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass

from backend.application.ports.food_catalog_repository import (
    FoodCatalogItem,
    FoodCatalogRepository,
    FoodCatalogRepositoryError,
    NewCustomFood,
)
from backend.domain.errors import ApplicationError
from backend.domain.meals import (
    BasisType,
    FoodDefinition,
    MealDomainError,
)


@dataclass(frozen=True)
class CustomFoodCommand:
    name: str
    basis_type: BasisType
    basis_amount: float
    unit: str
    calories: float
    carbs: float
    protein: float
    fat: float
    aliases: tuple[str, ...] = ()


class FoodCatalogServiceError(ApplicationError):
    def __init__(self, code: str, *, status_code: int) -> None:
        super().__init__(
            code=code,
            message=code,
            status_code=status_code,
            processing_mode="deterministic",
        )


class FoodCatalogService:
    def __init__(
        self,
        repository: FoodCatalogRepository,
        *,
        mutation_scope: Callable[[str], AbstractContextManager] | None = None,
    ) -> None:
        self.repository = repository
        self._mutation_scope = mutation_scope or (lambda _user_id: nullcontext())

    def search(
        self,
        user_id: str,
        query: str,
        *,
        limit: int = 20,
    ) -> tuple[FoodCatalogItem, ...]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise FoodCatalogServiceError(
                "FOOD_SEARCH_LIMIT_INVALID",
                status_code=422,
            )
        if not isinstance(query, str) or len(query) > 256:
            raise FoodCatalogServiceError(
                "FOOD_SEARCH_QUERY_INVALID",
                status_code=422,
            )
        return self.repository.search(user_id, query.strip(), limit=limit)

    def create_custom_food(
        self,
        user_id: str,
        command: CustomFoodCommand,
    ) -> FoodCatalogItem:
        try:
            definition = FoodDefinition(
                name=command.name,
                basis_type=command.basis_type,
                basis_amount=command.basis_amount,
                unit=command.unit,
                calories=command.calories,
                carbs=command.carbs,
                protein=command.protein,
                fat=command.fat,
                source="user_custom",
            )
        except MealDomainError as error:
            raise FoodCatalogServiceError(error.code, status_code=422) from None
        with self._mutation_scope(user_id):
            try:
                return self.repository.create_custom_food(
                    user_id,
                    NewCustomFood(
                        definition=definition,
                        aliases=command.aliases,
                    ),
                )
            except FoodCatalogRepositoryError as error:
                raise _repository_error(error) from None

    def set_favorite(
        self,
        user_id: str,
        food_id: str,
        favorite: bool,
    ) -> None:
        with self._mutation_scope(user_id):
            try:
                self.repository.set_favorite(user_id, food_id, favorite)
            except FoodCatalogRepositoryError as error:
                raise _repository_error(error) from None

    def record_usage(self, user_id: str, food_id: str) -> None:
        with self._mutation_scope(user_id):
            try:
                self.repository.record_usage(user_id, food_id)
            except FoodCatalogRepositoryError as error:
                raise _repository_error(error) from None


def _repository_error(
    error: FoodCatalogRepositoryError,
) -> FoodCatalogServiceError:
    status_code = 404 if error.code == "FOOD_NOT_VISIBLE" else 422
    return FoodCatalogServiceError(error.code, status_code=status_code)
