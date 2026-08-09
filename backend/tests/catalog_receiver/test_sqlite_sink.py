from pathlib import Path

from backend.catalog_receiver.mapping import load_mapping_profile
from backend.catalog_receiver.projectors import project_source
from backend.catalog_receiver.readers import read_source
from backend.catalog_receiver.sinks import SQLiteCatalogSink
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


ROOT = Path(__file__).parent
PROFILE = Path(__file__).parents[2] / "data/catalog/mappings/tfda-foods.v1.json"


def _database(tmp_path: Path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "receiver.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    return database


def test_sink_imports_and_idempotently_skips_normalized_foods(tmp_path: Path) -> None:
    database = _database(tmp_path)
    profile = load_mapping_profile(PROFILE)
    projected = project_source(read_source(ROOT / "fixtures/tfda-foods.csv"), profile)
    sink = SQLiteCatalogSink(database)

    first = sink.import_records(profile, projected.records)
    second = sink.import_records(profile, projected.records)

    assert first["status"] == "committed"
    assert first["inserted_count"] == 1
    assert second["status"] == "skipped"
    assert second["unchanged_count"] == 1
    with database.connection() as connection:
        row = connection.execute(
            "SELECT name, calories, source_name FROM food_catalog WHERE source_record_id = 'A001'"
        ).fetchone()
    assert dict(row) == {
        "name": "白饭",
        "calories": 130.0,
        "source_name": "Taiwan FDA Food Nutrient Database",
    }


def test_retirement_only_deactivates_public_rows_and_search(tmp_path: Path) -> None:
    database = _database(tmp_path)
    profile = load_mapping_profile(PROFILE)
    projected = project_source(read_source(ROOT / "fixtures/tfda-foods.csv"), profile)
    with database.transaction() as connection:
        common = (
            "2026-01-01", "Rice", "per_100g", 100, "g", 130, 28, 3, 1,
            "CC0", "source", "{}", "hash",
        )
        connection.execute(
            """
            INSERT INTO food_catalog (
                id, owner_user_id, source, source_name, source_record_id,
                dataset_version, name, basis_type, basis_amount, unit,
                calories, carbs, protein, fat, license, attribution,
                provenance_json, content_hash, active
            ) VALUES ('old-public', NULL, 'public', 'USDA FoodData Central', 'old', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            common,
        )
        connection.execute(
            """
            INSERT INTO food_catalog (
                id, owner_user_id, source, source_name, source_record_id,
                dataset_version, name, basis_type, basis_amount, unit,
                calories, carbs, protein, fat, license, attribution,
                provenance_json, content_hash, active
            ) VALUES ('old-private', 'user-1', 'user_custom', 'USDA FoodData Central', 'private', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            common,
        )
        connection.execute(
            "INSERT INTO catalog_search (catalog_kind, catalog_id, name, aliases, pinyin, source_tokens) VALUES ('food', 'old-public', 'Rice', '', '', '')"
        )

    result = SQLiteCatalogSink(database).import_records(profile, projected.records)

    assert result["retirement"]["deactivated_count"] == 1
    with database.connection() as connection:
        public = connection.execute("SELECT active FROM food_catalog WHERE id = 'old-public'").fetchone()
        private = connection.execute("SELECT active FROM food_catalog WHERE id = 'old-private'").fetchone()
        search_count = connection.execute(
            "SELECT COUNT(*) AS count FROM catalog_search WHERE catalog_id = 'old-public'"
        ).fetchone()["count"]
    assert public["active"] == 0
    assert private["active"] == 1
    assert search_count == 0
