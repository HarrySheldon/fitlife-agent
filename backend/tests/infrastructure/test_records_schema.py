import sqlite3

import pytest

from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


REQUIRED_TABLES = {
    "schema_migrations",
    "data_migrations",
    "user_profile_versions",
    "overall_goal_versions",
    "daily_target_versions",
    "daily_logs",
    "food_catalog",
    "exercise_catalog",
    "catalog_aliases",
    "catalog_favorites",
    "catalog_usage",
    "record_drafts",
    "meals",
    "meal_items",
    "training_sessions",
    "strength_exercises",
    "strength_sets",
    "cardio_items",
    "idempotency_keys",
    "catalog_imports",
    "catalog_search",
}


def test_records_schema_contains_required_tables_and_fts(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")

    run_migrations(database, RECORDS_MIGRATIONS)

    with database.connection() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        catalog_search_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'catalog_search'"
        ).fetchone()

    assert REQUIRED_TABLES <= tables
    assert catalog_search_sql is not None
    assert "VIRTUAL TABLE" in catalog_search_sql["sql"].upper()


def test_deleting_meal_cascades_to_its_items(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)

    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO meals (
                id, user_id, log_date, name, meal_type, position, entry_method
            ) VALUES (
                'meal-1', 'user-a', '2026-07-19', 'Lunch', 'lunch', 1, 'form'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO meal_items (
                id, meal_id, food_name, amount, unit, basis_type,
                calories, carbs, protein, fat, source
            ) VALUES (
                'item-1', 'meal-1', 'Rice', 100, 'g', 'per_100g',
                116, 25.9, 2.6, 0.3, 'user_custom'
            )
            """
        )
        connection.execute("DELETE FROM meals WHERE id = 'meal-1'")

    with database.connection() as connection:
        item_count = connection.execute(
            "SELECT COUNT(*) AS count FROM meal_items"
        ).fetchone()["count"]

    assert item_count == 0


def test_invalid_draft_json_is_rejected(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO record_drafts (
                    id, user_id, kind, schema_version, payload_json, expires_at
                ) VALUES (
                    'draft-1', 'user-a', 'meal', 1, 'not-json',
                    '2026-08-19T00:00:00Z'
                )
                """
            )


@pytest.mark.parametrize(
    ("food_id", "exercise_id"),
    [
        ("food-1", "exercise-1"),
        (None, None),
    ],
)
def test_catalog_alias_requires_exactly_one_catalog_target(
    tmp_path, food_id, exercise_id
):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)

    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO food_catalog (
                id, source, source_name, source_record_id, name, basis_type,
                basis_amount, unit, calories, carbs, protein, fat
            ) VALUES (
                'food-1', 'public', 'test-foods', '1', 'Rice', 'per_100g',
                100, 'g', 116, 25.9, 2.6, 0.3
            )
            """
        )
        connection.execute(
            """
            INSERT INTO exercise_catalog (
                id, source, source_name, source_record_id, name,
                exercise_type, primary_muscle
            ) VALUES (
                'exercise-1', 'public', 'test-exercises', '1', 'Squat',
                'strength', 'legs'
            )
            """
        )

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO catalog_aliases (
                    id, food_id, exercise_id, alias, normalized_alias, alias_kind
                ) VALUES ('alias-1', ?, ?, 'squat', 'squat', 'alias')
                """,
                (food_id, exercise_id),
            )


@pytest.mark.parametrize(
    ("calories", "carbs", "protein", "fat", "source"),
    [
        (799, 200, 100, 60, "manual"),
        (6001, 200, 100, 60, "manual"),
        (2000, -1, 100, 60, "manual"),
        (2000, 1001, 100, 60, "manual"),
        (2000, 200, 19, 60, "manual"),
        (2000, 200, 401, 60, "manual"),
        (2000, 200, 100, 9, "manual"),
        (2000, 200, 100, 301, "manual"),
        (2000, 200, 100, 60, "generated"),
    ],
)
def test_invalid_daily_target_boundaries_and_source_are_rejected(
    tmp_path, calories, carbs, protein, fat, source
):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO daily_target_versions (
                    id, user_id, calories, carbs, protein, fat, source,
                    effective_from
                ) VALUES (
                    'target-1', 'user-a', ?, ?, ?, ?, ?, '2026-07-19'
                )
                """,
                (calories, carbs, protein, fat, source),
            )


def test_duplicate_user_date_meal_position_is_rejected(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)

    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO meals (
                id, user_id, log_date, name, meal_type, position, entry_method
            ) VALUES (
                'meal-1', 'user-a', '2026-07-19', 'Lunch', 'lunch', 1, 'form'
            )
            """
        )

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO meals (
                    id, user_id, log_date, name, meal_type, position,
                    entry_method
                ) VALUES (
                    'meal-2', 'user-a', '2026-07-19', 'Snack', 'snack', 1,
                    'form'
                )
                """
            )


def test_key_lookup_and_foreign_key_indexes_exist(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)

    required_indexes = {
        "idx_profile_versions_user_effective": ("user_id", "effective_from"),
        "idx_goal_versions_user_effective": ("user_id", "effective_from"),
        "idx_target_versions_user_effective": ("user_id", "effective_from"),
        "idx_target_versions_profile": ("profile_version_id",),
        "idx_target_versions_goal": ("overall_goal_version_id",),
        "idx_daily_logs_target": ("target_version_id",),
        "idx_food_public_source": ("source_name", "source_record_id"),
        "idx_food_owner_name": ("owner_user_id", "name"),
        "idx_exercise_public_source": ("source_name", "source_record_id"),
        "idx_exercise_owner_name": ("owner_user_id", "name"),
        "idx_catalog_alias_food": ("food_id",),
        "idx_catalog_alias_exercise": ("exercise_id",),
        "idx_catalog_alias_normalized": ("normalized_alias",),
        "idx_catalog_usage_recent": (
            "user_id",
            "catalog_kind",
            "last_used_at",
        ),
        "idx_record_drafts_user_expiry": ("user_id", "expires_at"),
        "idx_meals_user_date": ("user_id", "log_date"),
        "idx_meal_items_meal": ("meal_id",),
        "idx_meal_items_catalog": ("catalog_food_id",),
        "idx_training_sessions_user_date": ("user_id", "log_date"),
        "idx_strength_exercises_session": ("session_id",),
        "idx_strength_exercises_catalog": ("catalog_exercise_id",),
        "idx_strength_sets_exercise": ("strength_exercise_id",),
        "idx_cardio_items_session": ("session_id",),
        "idx_cardio_items_catalog": ("catalog_exercise_id",),
    }

    with database.connection() as connection:
        actual_indexes = {
            index_name: tuple(
                column["name"]
                for column in connection.execute(
                    "SELECT name FROM pragma_index_info(?)", (index_name,)
                )
            )
            for index_name in required_indexes
        }
        daily_log_index_columns = {
            tuple(
                column["name"]
                for column in connection.execute(
                    "SELECT name FROM pragma_index_info(?)",
                    (index_row["name"],),
                )
            )
            for index_row in connection.execute("PRAGMA index_list('daily_logs')")
        }

    assert actual_indexes == required_indexes
    assert ("user_id", "log_date") in daily_log_index_columns


def test_records_migration_can_be_run_twice(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")

    run_migrations(database, RECORDS_MIGRATIONS)
    run_migrations(database, RECORDS_MIGRATIONS)

    with database.connection() as connection:
        applied = connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
        catalog_search_count = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM sqlite_master
            WHERE name = 'catalog_search'
            """
        ).fetchone()["count"]

    assert [tuple(row) for row in applied] == [(1, "create_records_schema")]
    assert catalog_search_count == 1
