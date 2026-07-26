from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import Mock

from backend.application.ports.smart_entry_repository import (
    SmartEntryDraft,
    SmartEntryDraftPayload,
)
from backend.application.ports.exercise_catalog_repository import (
    ExerciseCatalogItem,
)
from backend.application.ports.food_catalog_repository import FoodCatalogItem
from backend.application.use_cases.smart_entry import (
    SmartEntryService,
    resolve_candidates,
)
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


def test_create_draft_resolves_before_persistence_and_uses_lifecycle_lock():
    repository = Mock()
    repository.create_draft.return_value = Mock(spec=SmartEntryDraft)
    foods = Mock()
    foods.search.return_value = (_food("food-oats", "燕麦"),)
    exercises = Mock()
    events: list[str] = []

    @contextmanager
    def mutation_scope(user_id: str):
        events.append(f"enter:{user_id}")
        yield
        events.append(f"exit:{user_id}")

    service = SmartEntryService(
        repository,
        foods,
        exercises,
        clock=lambda: datetime(2026, 7, 26, 8, tzinfo=timezone.utc),
        mutation_scope=mutation_scope,
    )

    result = service.create_draft(
        "user-1",
        log_date="2026-07-26",
        raw_text="早餐：燕麦 50g",
        weight_kg=70,
    )

    assert result is repository.create_draft.return_value
    payload = repository.create_draft.call_args.args[1]
    assert payload.candidates[0].selected_catalog_id == "food-oats"
    assert repository.create_draft.call_args.kwargs["expires_at"] == (
        "2026-08-25T08:00:00Z"
    )
    assert events == ["enter:user-1", "exit:user-1"]


def test_confirm_draft_validates_uuid_and_passes_a_stable_fingerprint():
    repository = Mock()
    service = SmartEntryService(repository, Mock(), Mock())
    key = "2f8d44ca-9c6e-4cb4-b9af-3d8d991c2d33"

    service.confirm_draft(
        "user-1",
        "draft-1",
        expected_version=4,
        idempotency_key=key,
        timezone_name="Asia/Shanghai",
    )
    first = repository.confirm.call_args.kwargs
    service.confirm_draft(
        "user-1",
        "draft-1",
        expected_version=4,
        idempotency_key=key,
        timezone_name="Asia/Shanghai",
    )
    second = repository.confirm.call_args.kwargs

    assert first["idempotency_key"] == key
    assert first["request_fingerprint"] == second["request_fingerprint"]
    assert first["timezone_name"] == "Asia/Shanghai"


def test_update_reloads_selected_catalog_values_instead_of_trusting_client():
    repository = Mock()
    repository.update_draft.return_value = Mock(spec=SmartEntryDraft)
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
    tampered = replace(
        candidate,
        selected_catalog_id="oats-b",
        values={**candidate.values, "calories": 99_999},
    )
    service = SmartEntryService(repository, foods, exercises)

    service.update_draft(
        "user-1",
        "draft-1",
        expected_version=1,
        payload=SmartEntryDraftPayload(
            log_date="2026-07-26",
            raw_text="早餐：燕麦 50g",
            parser_version="smart-entry-parser-v1",
            candidates=(tampered,),
        ),
        weight_kg=70,
    )

    saved = repository.update_draft.call_args.kwargs["payload"].candidates[0]
    assert saved.selected_catalog_id == "oats-b"
    assert saved.values["calories"] == 190
    assert saved.issues == ()
