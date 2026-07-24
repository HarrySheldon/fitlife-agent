from __future__ import annotations

import pytest

from backend.application.ports.food_catalog_repository import (
    FoodCatalogRepositoryError,
    NewCustomFood,
)
from backend.domain.meals import FoodDefinition
from backend.infrastructure.repositories.sqlite_food_catalog_repository import (
    SQLiteFoodCatalogRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


def _database(tmp_path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "food-catalog.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    return database


def _insert_food(
    database: SQLiteDatabase,
    *,
    food_id: str,
    owner_user_id: str | None,
    name: str,
    active: bool = True,
    aliases: tuple[str, ...] = (),
) -> None:
    source = "public" if owner_user_id is None else "user_custom"
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO food_catalog (
                id, owner_user_id, source, source_name, source_record_id,
                dataset_version, name, basis_type, basis_amount, unit,
                calories, carbs, protein, fat, license, attribution,
                provenance_json, content_hash, active
            ) VALUES (
                ?, ?, ?, 'test-catalog', ?, 'test-v1', ?, 'per_100g', 100, 'g',
                100, 20, 3, 1, 'CC0-1.0', 'Test catalog', '{}', ?, ?
            )
            """,
            (
                food_id,
                owner_user_id,
                source,
                food_id,
                name,
                f"hash-{food_id}",
                int(active),
            ),
        )
        connection.execute(
            """
            INSERT INTO catalog_search (
                catalog_kind, catalog_id, name, aliases, pinyin, source_tokens
            ) VALUES ('food', ?, ?, '', '', '')
            """,
            (food_id, name),
        )
        for index, alias in enumerate(aliases):
            connection.execute(
                """
                INSERT INTO catalog_aliases (
                    id, food_id, alias, normalized_alias, alias_kind
                ) VALUES (?, ?, ?, ?, 'alias')
                """,
                (f"{food_id}-alias-{index}", food_id, alias, alias.casefold()),
            )
        if aliases:
            connection.execute(
                """
                UPDATE catalog_search
                SET aliases = ?
                WHERE catalog_kind = 'food' AND catalog_id = ?
                """,
                (" ".join(aliases), food_id),
            )


def test_search_exposes_public_and_owned_private_foods_but_not_inactive_or_foreign(
    tmp_path,
):
    database = _database(tmp_path)
    repository = SQLiteFoodCatalogRepository(database)
    _insert_food(
        database,
        food_id="public-rice",
        owner_user_id=None,
        name="Public rice",
    )
    _insert_food(
        database,
        food_id="private-a",
        owner_user_id="user-a",
        name="Private rice A",
    )
    _insert_food(
        database,
        food_id="private-b",
        owner_user_id="user-b",
        name="Private rice B",
    )
    _insert_food(
        database,
        food_id="inactive-public",
        owner_user_id=None,
        name="Inactive rice",
        active=False,
    )

    results = repository.search("user-a", "", limit=20)

    assert {item.id for item in results} == {"public-rice", "private-a"}
    assert all(item.active for item in results)


def test_search_matches_name_and_alias_prefixes_after_sanitizing_match_syntax(
    tmp_path,
):
    database = _database(tmp_path)
    repository = SQLiteFoodCatalogRepository(database)
    _insert_food(
        database,
        food_id="jasmine-rice",
        owner_user_id=None,
        name="Jasmine rice",
        aliases=("大米", "raw rice"),
    )
    _insert_food(
        database,
        food_id="rolled-oats",
        owner_user_id=None,
        name="Rolled oats",
        aliases=("燕麦",),
    )

    assert [item.id for item in repository.search("user-a", "jasm", limit=20)] == [
        "jasmine-rice"
    ]
    assert [item.id for item in repository.search("user-a", "大米", limit=20)] == [
        "jasmine-rice"
    ]
    assert [
        item.id
        for item in repository.search("user-a", '"raw-rice")*', limit=20)
    ] == ["jasmine-rice"]


def test_search_orders_recent_favorite_private_then_public_with_stable_ties(tmp_path):
    database = _database(tmp_path)
    repository = SQLiteFoodCatalogRepository(database)
    _insert_food(
        database,
        food_id="public-rice",
        owner_user_id=None,
        name="Rice",
    )
    _insert_food(
        database,
        food_id="public-oats",
        owner_user_id=None,
        name="Oats",
    )
    _insert_food(
        database,
        food_id="private-noodles",
        owner_user_id="user-a",
        name="Noodles",
    )
    _insert_food(
        database,
        food_id="public-beans",
        owner_user_id=None,
        name="Beans",
    )
    _insert_food(
        database,
        food_id="public-apples",
        owner_user_id=None,
        name="Apples",
    )

    repository.set_favorite("user-a", "public-rice", True)
    repository.record_usage("user-a", "public-oats")

    results = repository.search("user-a", "", limit=20)

    assert [item.id for item in results] == [
        "public-oats",
        "public-rice",
        "private-noodles",
        "public-apples",
        "public-beans",
    ]
    assert [item.rank_group for item in results] == [0, 1, 2, 3, 3]


def test_favorite_and_usage_writes_reject_invisible_foods(tmp_path):
    database = _database(tmp_path)
    repository = SQLiteFoodCatalogRepository(database)
    _insert_food(
        database,
        food_id="private-b",
        owner_user_id="user-b",
        name="Private B",
    )
    _insert_food(
        database,
        food_id="inactive-public",
        owner_user_id=None,
        name="Inactive",
        active=False,
    )

    actions = (
        lambda food_id: repository.set_favorite("user-a", food_id, True),
        lambda food_id: repository.set_favorite("user-a", food_id, False),
        lambda food_id: repository.record_usage("user-a", food_id),
    )
    for food_id in ("private-b", "inactive-public"):
        for action in actions:
            with pytest.raises(FoodCatalogRepositoryError) as captured:
                action(food_id)
            assert captured.value.code == "FOOD_NOT_VISIBLE"


def test_create_custom_food_is_owned_searchable_and_source_aware(tmp_path):
    database = _database(tmp_path)
    repository = SQLiteFoodCatalogRepository(
        database,
        id_factory=iter(
            ("custom-food", "alias-zh", "alias-en", "alias-long")
        ).__next__,
    )
    custom = NewCustomFood(
        definition=FoodDefinition(
            name="My oat bowl",
            basis_type="per_serving",
            basis_amount=1,
            unit="bowl",
            calories=410,
            carbs=62,
            protein=24,
            fat=9,
            source="user_custom",
        ),
        aliases=("我的燕麦碗", "oat breakfast", "香喷喷白米饭碗"),
    )

    created = repository.create_custom_food("user-a", custom)

    assert created.id == "custom-food"
    assert created.owner_user_id == "user-a"
    assert created.source == "user_custom"
    assert created.source_name == "user-custom"
    assert created.aliases == (
        "我的燕麦碗",
        "oat breakfast",
        "香喷喷白米饭碗",
    )
    assert [
        item.id
        for item in repository.search("user-a", "燕麦", limit=20)
    ] == ["custom-food"]
    assert [
        item.id
        for item in repository.search("user-a", "白米饭", limit=20)
    ] == ["custom-food"]
    assert repository.search("user-b", "燕麦", limit=20) == ()


def test_create_custom_food_rejects_non_custom_source(tmp_path):
    repository = SQLiteFoodCatalogRepository(_database(tmp_path))
    invalid = NewCustomFood(
        definition=FoodDefinition(
            name="Public-like food",
            basis_type="per_100g",
            basis_amount=100,
            unit="g",
            calories=100,
            carbs=20,
            protein=3,
            fat=1,
            source="public",
        ),
    )

    with pytest.raises(FoodCatalogRepositoryError) as captured:
        repository.create_custom_food("user-a", invalid)

    assert captured.value.code == "CUSTOM_FOOD_SOURCE_INVALID"
