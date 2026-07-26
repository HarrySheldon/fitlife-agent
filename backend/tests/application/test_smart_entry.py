from unittest.mock import Mock

from backend.application.ports.exercise_catalog_repository import (
    ExerciseCatalogItem,
)
from backend.application.ports.food_catalog_repository import FoodCatalogItem
from backend.application.use_cases.smart_entry import resolve_candidates
from backend.domain.smart_entry import parse_entry_text


def _food(
    item_id: str,
    name: str,
    *,
    aliases: tuple[str, ...] = (),
) -> FoodCatalogItem:
    return FoodCatalogItem(
        id=item_id,
        owner_user_id=None,
        source="public",
        source_name="USDA FoodData Central",
        source_record_id=item_id,
        dataset_version="2026-01",
        name=name,
        basis_type="per_100g",
        basis_amount=100,
        unit="g",
        calories=380,
        carbs=68,
        protein=13,
        fat=7,
        license="CC0-1.0",
        attribution="USDA",
        provenance={"source_url": "https://fdc.nal.usda.gov/"},
        content_hash="food-hash",
        active=True,
        aliases=aliases,
        is_favorite=False,
        use_count=0,
        last_used_at=None,
        rank_group=2,
    )


def _exercise(item_id: str, name: str) -> ExerciseCatalogItem:
    return ExerciseCatalogItem(
        id=item_id,
        owner_user_id=None,
        source="public",
        source_name="Compendium of Physical Activities",
        source_record_id=item_id,
        dataset_version="2024",
        name=name,
        exercise_type="cardio",
        primary_muscle="cardiovascular",
        secondary_muscles=("legs",),
        met=8,
        license="source-terms",
        attribution="Adult Compendium",
        provenance={"source_url": "https://pacompendium.com/"},
        content_hash="exercise-hash",
        active=True,
        aliases=("跑步", "running"),
        is_favorite=False,
        use_count=0,
        last_used_at=None,
        rank_group=2,
    )


def test_resolve_candidates_uses_unique_exact_catalog_matches_and_formulas():
    foods = Mock()
    foods.search.return_value = (_food("food-oats", "燕麦"),)
    exercises = Mock()
    exercises.search.return_value = (_exercise("exercise-run", "跑步"),)

    candidates = resolve_candidates(
        "user-1",
        parse_entry_text("早餐：燕麦 50g\n有氧：跑步 30分钟"),
        food_catalog=foods,
        exercise_catalog=exercises,
        weight_kg=70,
    )

    assert candidates[0].selected_catalog_id == "food-oats"
    assert candidates[0].values["calories"] == 190
    assert candidates[0].values["source"] == "public"
    assert candidates[0].provenance["license"] == "CC0-1.0"
    assert candidates[1].selected_catalog_id == "exercise-run"
    assert candidates[1].values["estimated_calories"] == 294
    assert candidates[1].values["is_estimate"] is True


def test_resolve_candidates_never_guesses_between_ambiguous_aliases():
    foods = Mock()
    foods.search.return_value = (
        _food("oats-a", "Rolled oats", aliases=("燕麦",)),
        _food("oats-b", "Steel-cut oats", aliases=("燕麦",)),
    )
    exercises = Mock()

    candidate = resolve_candidates(
        "user-1",
        parse_entry_text("早餐：燕麦 50g"),
        food_catalog=foods,
        exercise_catalog=exercises,
        weight_kg=70,
    )[0]

    assert candidate.selected_catalog_id is None
    assert {item.id for item in candidate.catalog_choices} == {
        "oats-a",
        "oats-b",
    }
    assert "SMART_ENTRY_CATALOG_AMBIGUOUS" in candidate.issues


def test_resolve_candidates_keeps_fuzzy_results_as_unselected_choices():
    foods = Mock()
    foods.search.return_value = (_food("oats", "Rolled oats"),)
    exercises = Mock()

    candidate = resolve_candidates(
        "user-1",
        parse_entry_text("早餐：燕麦 50g"),
        food_catalog=foods,
        exercise_catalog=exercises,
        weight_kg=None,
    )[0]

    assert candidate.selected_catalog_id is None
    assert [item.id for item in candidate.catalog_choices] == ["oats"]
    assert "SMART_ENTRY_CATALOG_UNMATCHED" in candidate.issues
