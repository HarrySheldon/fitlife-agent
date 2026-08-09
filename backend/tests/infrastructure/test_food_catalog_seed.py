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


SEED_PATH = Path(__file__).parents[2] / "data" / "catalog" / "foods.zh-CN.v1.json"
EXPECTED_COUNT = 2_128
REPRESENTATIVE_FOODS = {
    "A0550601": (182, 41.0, 3.1, 0.3, "白飯"),
    "D0800201": (87, 23.3, 1.3, 0.3, "北蕉(0天,绿皮)"),
    "E5800402": (33, 6.5, 3.4, 0.4, "Broccoli"),
    "I0402402": (117, 0.6, 23.3, 1.9, "去皮清肉(肉鸡)"),
}


def _database(tmp_path: Path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "food-seed.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    return database


def test_seed_snapshot_is_complete_and_auditable() -> None:
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["source_name"] == "Taiwan FDA Food Nutrient Database"
    assert payload["dataset_version"] == "2025-12-22"
    assert len(payload["foods"]) == EXPECTED_COUNT
    by_id = {record["source_record_id"]: record for record in payload["foods"]}
    assert set(REPRESENTATIVE_FOODS) <= set(by_id)
    for source_id, (calories, carbs, protein, fat, _query) in REPRESENTATIVE_FOODS.items():
        record = by_id[source_id]
        assert record["source_name"] == payload["source_name"]
        assert record["license"] == "Taiwan Government Open Data License 1.0"
        assert record["attribution"] == "Taiwan Food and Drug Administration"
        assert record["provenance"]["profile"] == "tfda-foods@1.0.0"
        assert all(isinstance(alias, str) for alias in record["aliases"])
        assert (record["calories"], record["carbs"], record["protein"], record["fat"]) == (
            calories,
            carbs,
            protein,
            fat,
        )


def test_seed_is_idempotent_and_multilingual_searchable(tmp_path: Path) -> None:
    database = _database(tmp_path)

    first = seed_bundled_foods(database, SEED_PATH)
    second = seed_bundled_foods(database, SEED_PATH)

    assert first.inserted_count == EXPECTED_COUNT
    assert second.unchanged_count == EXPECTED_COUNT
    assert second.skipped is True
    repository = SQLiteFoodCatalogRepository(database)
    for source_id, expected in REPRESENTATIVE_FOODS.items():
        results = repository.search("user-a", expected[4], limit=50)
        match = next(item for item in results if item.source_record_id == source_id)
        assert (match.calories, match.carbs, match.protein, match.fat) == expected[:4]
        assert match.source_name == "Taiwan FDA Food Nutrient Database"
        assert match.dataset_version == "2025-12-22"
        assert len(match.content_hash or "") == 64


def test_new_version_upserts_and_rebuilds_search_without_touching_unrelated_rows(tmp_path: Path) -> None:
    database = _database(tmp_path)
    seed_bundled_foods(database, SEED_PATH)
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO catalog_search (catalog_kind, catalog_id, name, aliases, pinyin, source_tokens)
            VALUES ('food', 'unrelated-food', 'Unrelated', '', '', '')
            """
        )
        before = connection.execute(
            "SELECT rowid FROM catalog_search WHERE catalog_id = 'unrelated-food'"
        ).fetchone()["rowid"]
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    payload["dataset_version"] = "2025-12-23"
    for food in payload["foods"]:
        food["dataset_version"] = "2025-12-23"
    payload["foods"][0]["aliases"].append("receiver-updated-food")
    changed_path = tmp_path / "changed-foods.json"
    changed_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = seed_bundled_foods(database, changed_path)

    assert result.updated_count == EXPECTED_COUNT
    changed = SQLiteFoodCatalogRepository(database).search(
        "user-a", "receiver-updated-food", limit=20
    )
    assert len(changed) == 1
    with database.connection() as connection:
        after = connection.execute(
            "SELECT rowid FROM catalog_search WHERE catalog_id = 'unrelated-food'"
        ).fetchone()["rowid"]
    assert after == before


def test_removed_seed_records_are_deactivated(tmp_path: Path) -> None:
    database = _database(tmp_path)
    seed_bundled_foods(database, SEED_PATH)
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    payload["dataset_version"] = "2025-12-23"
    payload["foods"] = []
    removed_path = tmp_path / "removed-foods.json"
    removed_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    result = seed_bundled_foods(database, removed_path)

    assert result.deactivated_count == EXPECTED_COUNT
    assert SQLiteFoodCatalogRepository(database).search("user-a", "白飯", limit=20) == ()


def test_seed_rejects_checksum_drift_for_completed_version(tmp_path: Path) -> None:
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
        (lambda payload: payload.update({"schema_version": 2}), "FOOD_SEED_SCHEMA_VERSION_UNSUPPORTED"),
        (lambda payload: payload["foods"].append(dict(payload["foods"][0])), "FOOD_SEED_SOURCE_ID_DUPLICATE"),
    ],
)
def test_seed_rejects_invalid_snapshot(tmp_path: Path, mutation, code: str) -> None:
    database = _database(tmp_path)
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    mutation(payload)
    invalid = tmp_path / "invalid-foods.json"
    invalid.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError) as captured:
        seed_bundled_foods(database, invalid)

    assert str(captured.value) == code
