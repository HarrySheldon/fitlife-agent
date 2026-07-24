from unittest.mock import Mock

import pytest

from backend.application.ports.food_catalog_repository import (
    FoodCatalogRepositoryError,
)
from backend.application.use_cases.food_catalog import (
    CustomFoodCommand,
    FoodCatalogService,
    FoodCatalogServiceError,
)


def _service() -> tuple[FoodCatalogService, Mock]:
    repository = Mock()
    return FoodCatalogService(repository), repository


def test_create_custom_food_builds_complete_user_owned_definition():
    service, repository = _service()
    repository.create_custom_food.return_value = object()
    command = CustomFoodCommand(
        name="Oat bowl",
        basis_type="per_serving",
        basis_amount=1,
        unit="bowl",
        calories=410,
        carbs=62,
        protein=24,
        fat=9,
        aliases=("燕麦碗",),
    )

    created = service.create_custom_food("user-a", command)

    assert created is repository.create_custom_food.return_value
    saved = repository.create_custom_food.call_args.args[1]
    assert saved.definition.source == "user_custom"
    assert saved.definition.calories == 410
    assert saved.aliases == ("燕麦碗",)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("calories", None, "FOOD_NUTRIENT_INVALID"),
        ("carbs", -1, "FOOD_NUTRIENT_INVALID"),
        ("protein", float("nan"), "FOOD_NUTRIENT_INVALID"),
        ("fat", float("inf"), "FOOD_NUTRIENT_INVALID"),
    ],
)
def test_create_custom_food_rejects_incomplete_nutrients(field, value, code):
    service, repository = _service()
    values = {
        "name": "Oat bowl",
        "basis_type": "per_serving",
        "basis_amount": 1,
        "unit": "bowl",
        "calories": 410,
        "carbs": 62,
        "protein": 24,
        "fat": 9,
    }
    values[field] = value

    with pytest.raises(FoodCatalogServiceError) as captured:
        service.create_custom_food("user-a", CustomFoodCommand(**values))

    assert captured.value.code == code
    assert captured.value.status_code == 422
    repository.create_custom_food.assert_not_called()


@pytest.mark.parametrize("limit", [0, 51])
def test_search_rejects_limit_outside_supported_range(limit):
    service, repository = _service()

    with pytest.raises(FoodCatalogServiceError) as captured:
        service.search("user-a", "rice", limit=limit)

    assert captured.value.code == "FOOD_SEARCH_LIMIT_INVALID"
    assert captured.value.status_code == 422
    repository.search.assert_not_called()


def test_search_rejects_excessively_long_query():
    service, repository = _service()

    with pytest.raises(FoodCatalogServiceError) as captured:
        service.search("user-a", "r" * 257, limit=20)

    assert captured.value.code == "FOOD_SEARCH_QUERY_INVALID"
    repository.search.assert_not_called()


def test_favorite_maps_invisible_food_to_not_found():
    service, repository = _service()
    repository.set_favorite.side_effect = FoodCatalogRepositoryError(
        "FOOD_NOT_VISIBLE"
    )

    with pytest.raises(FoodCatalogServiceError) as captured:
        service.set_favorite("user-a", "foreign-food", True)

    assert captured.value.code == "FOOD_NOT_VISIBLE"
    assert captured.value.status_code == 404
