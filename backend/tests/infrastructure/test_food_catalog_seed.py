from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.infrastructure.catalog.import_ledger import CatalogImportError
from backend.infrastructure.catalog.seed_foods import seed_bundled_foods
from backend.infrastructure.repositories.sqlite_food_catalog_repository import (
    SQLiteFoodCatalogRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


SEED_PATH = (
    Path(__file__).parents[2]
    / "data"
    / "catalog"
    / "foods.zh-CN.v1.json"
)

EXPECTED_FOODS = {
    "169756": (365, 79.95, 7.13, 0.66, "dami"),
    "173424": (155, 1.12, 12.6, 10.6, "boiled egg"),
    "171477": (165, 0, 31, 3.57, "chicken breast"),
    "173944": (89, 22.8, 1.09, 0.33, "banana"),
    "171265": (61, 4.8, 3.15, 3.25, "whole milk"),
    "173904": (379, 67.7, 13.2, 6.52, "oats"),
    "169967": (35, 7.18, 2.38, 0.41, "broccoli"),
    "172475": (144, 2.78, 17.3, 8.72, "firm tofu"),
}


def _database(tmp_path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "food-seed.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    return database


def test_seed_records_are_self_contained_auditable_documents():
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    assert {
        record["source_record_id"] for record in payload["foods"]
    } == set(EXPECTED_FOODS)
    for record in payload["foods"]:
        assert record["source_name"] == "USDA FoodData Central"
        assert record["dataset_version"] == "2026-07-25"
        assert record["license"] == "CC0-1.0"
        assert record["attribution"] == "USDA FoodData Central"
        assert all(isinstance(alias, str) for alias in record["aliases"])
        assert record["provenance"]["source_url"].endswith(
            f'/{record["source_record_id"]}/nutrients'
        )
        calories, carbs, protein, fat, _ = EXPECTED_FOODS[
            record["source_record_id"]
        ]
        assert (
            record["calories"],
            record["carbs"],
            record["protein"],
            record["fat"],
        ) == (calories, carbs, protein, fat)


def test_seed_is_idempotent_searchable_and_preserves_source_metadata(tmp_path):
    database = _database(tmp_path)

    first = seed_bundled_foods(database, SEED_PATH)
    second = seed_bundled_foods(database, SEED_PATH)

    assert first.inserted_count == len(EXPECTED_FOODS)
    assert first.updated_count == 0
    assert second.inserted_count == 0
    assert second.updated_count == 0
    assert second.unchanged_count == len(EXPECTED_FOODS)
    repository = SQLiteFoodCatalogRepository(database)
    for source_record_id, expected in EXPECTED_FOODS.items():
        results = repository.search("user-a", expected[4], limit=20)
        assert len(results) == 1
        assert results[0].source_record_id == source_record_id
    rice = repository.search("user-a", "dami", limit=20)[0]
    assert rice.source == "public"
    assert rice.source_name == "USDA FoodData Central"
    assert rice.source_record_id == "169756"
    assert rice.dataset_version == "2026-07-25"
    assert rice.license == "CC0-1.0"
    assert rice.attribution == "USDA FoodData Central"
    assert rice.calories == 365
    assert rice.carbs == 79.95
    assert rice.protein == 7.13
    assert rice.fat == 0.66
    assert rice.content_hash is not None
    assert len(rice.content_hash) == 64


def test_changed_seed_upserts_food_and_rebuilds_only_its_search_row(tmp_path):
    database = _database(tmp_path)
    seed_bundled_foods(database, SEED_PATH)
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO catalog_search (
                catalog_kind, catalog_id, name, aliases, pinyin, source_tokens
            ) VALUES ('food', 'unrelated-food', 'Unrelated', '', '', '')
            """
        )
    with database.connection() as connection:
        before_seed_rowid = connection.execute(
            """
            SELECT rowid FROM catalog_search
            WHERE catalog_kind = 'food' AND catalog_id = (
                SELECT id FROM food_catalog
                WHERE source_name = 'USDA FoodData Central'
                  AND source_record_id = '169756'
            )
            """
        ).fetchone()["rowid"]
        before_unrelated_rowid = connection.execute(
            """
            SELECT rowid FROM catalog_search
            WHERE catalog_kind = 'food' AND catalog_id = 'unrelated-food'
            """
        ).fetchone()["rowid"]

    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    payload["dataset_version"] = "2026-07-26"
    for food in payload["foods"]:
        food["dataset_version"] = "2026-07-26"
    payload["foods"][0]["calories"] = 366
    payload["foods"][0]["aliases"].append("稻米")
    changed_path = tmp_path / "changed-foods.json"
    changed_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    result = seed_bundled_foods(database, changed_path)

    assert result.inserted_count == 0
    assert result.updated_count == len(EXPECTED_FOODS)
    changed = SQLiteFoodCatalogRepository(database).search(
        "user-a",
        "稻米",
        limit=20,
    )
    assert len(changed) == 1
    assert changed[0].calories == 366
    with database.connection() as connection:
        after_seed_rowid = connection.execute(
            """
            SELECT rowid FROM catalog_search
            WHERE catalog_kind = 'food' AND catalog_id = ?
            """,
            (changed[0].id,),
        ).fetchone()["rowid"]
        after_unrelated_rowid = connection.execute(
            """
            SELECT rowid FROM catalog_search
            WHERE catalog_kind = 'food' AND catalog_id = 'unrelated-food'
            """
        ).fetchone()["rowid"]
    assert after_seed_rowid != before_seed_rowid
    assert after_unrelated_rowid == before_unrelated_rowid


def test_removed_seed_record_is_deactivated_and_no_longer_searchable(tmp_path):
    database = _database(tmp_path)
    seed_bundled_foods(database, SEED_PATH)
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    payload["dataset_version"] = "2026-07-26"
    payload["foods"] = []
    removed_path = tmp_path / "removed-foods.json"
    removed_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    result = seed_bundled_foods(database, removed_path)

    assert result.deactivated_count == len(EXPECTED_FOODS)
    assert SQLiteFoodCatalogRepository(database).search(
        "user-a",
        "dami",
        limit=20,
    ) == ()
    with database.connection() as connection:
        active = connection.execute(
            """
            SELECT active FROM food_catalog
            WHERE source_name = 'USDA FoodData Central'
              AND source_record_id = '169756'
            """
        ).fetchone()["active"]
    assert active == 0


def test_seed_rejects_changed_content_for_completed_version(tmp_path):
    database = _database(tmp_path)
    seed_bundled_foods(database, SEED_PATH)
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    payload["foods"][0]["calories"] += 1
    changed = tmp_path / "drifted-foods.json"
    changed.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(CatalogImportError) as captured:
        seed_bundled_foods(database, changed)

    assert captured.value.code == "CATALOG_IMPORT_CHECKSUM_MISMATCH"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda payload: payload.update({"schema_version": 2}),
            "FOOD_SEED_SCHEMA_VERSION_UNSUPPORTED",
        ),
        (
            lambda payload: payload["foods"].append(
                dict(payload["foods"][0])
            ),
            "FOOD_SEED_SOURCE_ID_DUPLICATE",
        ),
    ],
)
def test_seed_rejects_unsupported_schema_and_duplicate_source_identity(
    tmp_path,
    mutation,
    code,
):
    database = _database(tmp_path)
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    mutation(payload)
    invalid_path = tmp_path / "invalid-foods.json"
    invalid_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as captured:
        seed_bundled_foods(database, invalid_path)

    assert str(captured.value) == code
