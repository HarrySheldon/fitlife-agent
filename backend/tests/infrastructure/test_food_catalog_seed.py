from __future__ import annotations

import json
from pathlib import Path

import pytest

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


def _database(tmp_path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "food-seed.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    return database


def test_seed_records_are_self_contained_auditable_documents():
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    record = payload["foods"][0]

    assert record["source_name"] == "USDA FoodData Central"
    assert record["source_record_id"] == "169756"
    assert record["dataset_version"] == "2026-07-24"
    assert record["license"] == "CC0-1.0"
    assert record["attribution"] == "USDA FoodData Central"
    assert all(isinstance(alias, str) for alias in record["aliases"])


def test_seed_is_idempotent_searchable_and_preserves_source_metadata(tmp_path):
    database = _database(tmp_path)

    first = seed_bundled_foods(database, SEED_PATH)
    second = seed_bundled_foods(database, SEED_PATH)

    assert first.inserted_count == 1
    assert first.updated_count == 0
    assert second.inserted_count == 0
    assert second.updated_count == 0
    assert second.unchanged_count == 1
    results = SQLiteFoodCatalogRepository(database).search(
        "user-a",
        "dami",
        limit=20,
    )
    assert len(results) == 1
    rice = results[0]
    assert rice.source == "public"
    assert rice.source_name == "USDA FoodData Central"
    assert rice.source_record_id == "169756"
    assert rice.dataset_version == "2026-07-24"
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
    payload["foods"][0]["calories"] = 366
    payload["foods"][0]["aliases"].append("稻米")
    changed_path = tmp_path / "changed-foods.json"
    changed_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    result = seed_bundled_foods(database, changed_path)

    assert result.inserted_count == 0
    assert result.updated_count == 1
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
    payload["foods"] = []
    removed_path = tmp_path / "removed-foods.json"
    removed_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    result = seed_bundled_foods(database, removed_path)

    assert result.deactivated_count == 1
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
