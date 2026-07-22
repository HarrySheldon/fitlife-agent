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

V1_CHECKSUM = "80f42c094b90e2dec79132a1c6edf8f214265de2565e2eecd999e5f93290e0fa"


def _insert_profile(connection, profile_id="profile-1", user_id="user-a"):
    connection.execute(
        """
        INSERT INTO user_profile_versions (
            id, user_id, age, height_cm, weight_kg, energy_parameter,
            activity_level, effective_from
        ) VALUES (?, ?, 30, 175, 70, 'neutral', 'moderate', '2026-07-01')
        """,
        (profile_id, user_id),
    )


def _insert_goal(connection, goal_id="goal-1", user_id="user-a"):
    connection.execute(
        """
        INSERT INTO overall_goal_versions (
            id, user_id, goal, effective_from
        ) VALUES (?, ?, 'maintenance', '2026-07-01')
        """,
        (goal_id, user_id),
    )


def _insert_target(
    connection,
    target_id="target-1",
    user_id="user-a",
    profile_id=None,
    goal_id=None,
):
    connection.execute(
        """
        INSERT INTO daily_target_versions (
            id, user_id, profile_version_id, overall_goal_version_id,
            calories, carbs, protein, fat, source, effective_from
        ) VALUES (?, ?, ?, ?, 2000, 200, 100, 60, 'manual', '2026-07-01')
        """,
        (target_id, user_id, profile_id, goal_id),
    )


def _insert_food(
    connection,
    food_id="food-1",
    source="public",
    owner_user_id=None,
    source_name="test-foods",
    source_record_id="1",
):
    connection.execute(
        """
        INSERT INTO food_catalog (
            id, owner_user_id, source, source_name, source_record_id, name,
            basis_type, basis_amount, unit, calories, carbs, protein, fat
        ) VALUES (
            ?, ?, ?, ?, ?, 'Rice', 'per_100g', 100, 'g', 116, 25.9, 2.6, 0.3
        )
        """,
        (food_id, owner_user_id, source, source_name, source_record_id),
    )


def _insert_exercise(
    connection,
    exercise_id="exercise-1",
    source="public",
    owner_user_id=None,
    source_name="test-exercises",
    source_record_id="1",
    exercise_type="strength",
):
    connection.execute(
        """
        INSERT INTO exercise_catalog (
            id, owner_user_id, source, source_name, source_record_id, name,
            exercise_type, primary_muscle
        ) VALUES (
            ?, ?, ?, ?, ?, 'Squat', ?, 'legs'
        )
        """,
        (
            exercise_id,
            owner_user_id,
            source,
            source_name,
            source_record_id,
            exercise_type,
        ),
    )


def _insert_meal(connection, meal_id="meal-1", user_id="user-a"):
    connection.execute(
        """
        INSERT INTO meals (
            id, user_id, log_date, name, meal_type, position, entry_method
        ) VALUES (?, ?, '2026-07-19', 'Lunch', 'lunch', 1, 'form')
        """,
        (meal_id, user_id),
    )


def _insert_session(connection, session_id="session-1", user_id="user-a"):
    connection.execute(
        """
        INSERT INTO training_sessions (
            id, user_id, log_date, title, entry_method
        ) VALUES (?, ?, '2026-07-01', 'Training', 'form')
        """,
        (session_id, user_id),
    )


def _seed_v1_upgrade_violation(connection, violation):
    if violation == "json_array_profile":
        _insert_profile(connection)
        connection.execute(
            "UPDATE user_profile_versions SET safety_conditions_json = '{}'"
        )
        return "user_profile_versions", "profile-1"

    if violation == "json_object_food":
        _insert_food(connection)
        connection.execute("UPDATE food_catalog SET provenance_json = '[]'")
        return "food_catalog", "food-1"

    _insert_food(
        connection,
        food_id="food-private-b",
        source="user_custom",
        owner_user_id="user-b",
        source_record_id="private-b",
    )
    _insert_exercise(
        connection,
        exercise_id="strength-private-b",
        source="user_custom",
        owner_user_id="user-b",
        source_record_id="strength-private-b",
        exercise_type="strength",
    )
    _insert_exercise(
        connection,
        exercise_id="cardio-private-b",
        source="user_custom",
        owner_user_id="user-b",
        source_record_id="cardio-private-b",
        exercise_type="cardio",
    )
    _insert_exercise(
        connection,
        exercise_id="public-strength",
        source_record_id="public-strength",
        exercise_type="strength",
    )
    _insert_exercise(
        connection,
        exercise_id="public-cardio",
        source_record_id="public-cardio",
        exercise_type="cardio",
    )
    _insert_meal(connection)
    _insert_session(connection)

    statements = {
        "favorite_owner": (
            "catalog_favorites",
            "favorite-1",
            """
            INSERT INTO catalog_favorites (id, user_id, food_id)
            VALUES ('favorite-1', 'user-a', 'food-private-b')
            """,
        ),
        "usage_owner": (
            "catalog_usage",
            "usage-1",
            """
            INSERT INTO catalog_usage (id, user_id, food_id)
            VALUES ('usage-1', 'user-a', 'food-private-b')
            """,
        ),
        "meal_owner": (
            "meal_items",
            "meal-item-1",
            """
            INSERT INTO meal_items (
                id, meal_id, catalog_food_id, food_name, amount, unit,
                basis_type, calories, carbs, protein, fat, source
            ) VALUES (
                'meal-item-1', 'meal-1', 'food-private-b', 'Rice', 100, 'g',
                'per_100g', 116, 25.9, 2.6, 0.3, 'user_custom'
            )
            """,
        ),
        "strength_owner": (
            "strength_exercises",
            "strength-1",
            """
            INSERT INTO strength_exercises (
                id, session_id, catalog_exercise_id, exercise_name,
                primary_muscle, position
            ) VALUES (
                'strength-1', 'session-1', 'strength-private-b',
                'Squat', 'legs', 1
            )
            """,
        ),
        "strength_subtype": (
            "strength_exercises",
            "strength-1",
            """
            INSERT INTO strength_exercises (
                id, session_id, catalog_exercise_id, exercise_name,
                primary_muscle, position
            ) VALUES (
                'strength-1', 'session-1', 'public-cardio',
                'Running', 'legs', 1
            )
            """,
        ),
        "cardio_owner": (
            "cardio_items",
            "cardio-1",
            """
            INSERT INTO cardio_items (
                id, session_id, catalog_exercise_id, activity_name,
                duration_min, position
            ) VALUES (
                'cardio-1', 'session-1', 'cardio-private-b',
                'Running', 20, 1
            )
            """,
        ),
        "cardio_subtype": (
            "cardio_items",
            "cardio-1",
            """
            INSERT INTO cardio_items (
                id, session_id, catalog_exercise_id, activity_name,
                duration_min, position
            ) VALUES (
                'cardio-1', 'session-1', 'public-strength',
                'Squat', 20, 1
            )
            """,
        ),
        "json_array_strength": (
            "strength_exercises",
            "strength-1",
            """
            INSERT INTO strength_exercises (
                id, session_id, exercise_name, primary_muscle,
                secondary_muscles_json, position
            ) VALUES (
                'strength-1', 'session-1', 'Squat', 'legs', '{}', 1
            )
            """,
        ),
    }
    table_name, row_id, statement = statements[violation]
    connection.execute(statement)
    return table_name, row_id


def _seed_valid_deferred_child(connection, case):
    if case in ("favorite", "usage"):
        _insert_food(connection)
        table_name = {
            "favorite": "catalog_favorites",
            "usage": "catalog_usage",
        }[case]
        connection.execute(
            f"""
            INSERT INTO {table_name} (id, user_id, food_id)
            VALUES ('child-1', 'user-a', 'food-1')
            """
        )
        return

    if case == "meal":
        _insert_food(connection)
        _insert_meal(connection)
        connection.execute(
            """
            INSERT INTO meal_items (
                id, meal_id, catalog_food_id, food_name, amount, unit,
                basis_type, calories, carbs, protein, fat, source
            ) VALUES (
                'child-1', 'meal-1', 'food-1', 'Rice', 100, 'g',
                'per_100g', 116, 25.9, 2.6, 0.3, 'public'
            )
            """
        )
        return

    item_kind = case.split("_", maxsplit=1)[0]
    _insert_session(connection)
    _insert_exercise(connection, exercise_type=item_kind)
    if item_kind == "strength":
        connection.execute(
            """
            INSERT INTO strength_exercises (
                id, session_id, catalog_exercise_id, exercise_name,
                primary_muscle, position
            ) VALUES ('child-1', 'session-1', 'exercise-1', 'Squat', 'legs', 1)
            """
        )
    else:
        connection.execute(
            """
            INSERT INTO cardio_items (
                id, session_id, catalog_exercise_id, activity_name,
                duration_min, position
            ) VALUES ('child-1', 'session-1', 'exercise-1', 'Run', 20, 1)
            """
        )


def _write_deferred_child(connection, case, operation):
    if case in ("favorite", "usage"):
        table_name = {
            "favorite": "catalog_favorites",
            "usage": "catalog_usage",
        }[case]
        if operation == "insert":
            connection.execute(
                f"""
                INSERT INTO {table_name} (id, user_id, food_id)
                VALUES ('child-1', 'user-a', 'late-food')
                """
            )
        else:
            connection.execute(
                f"UPDATE {table_name} SET food_id = 'late-food' WHERE id = 'child-1'"
            )
        return

    if case == "meal":
        if operation == "insert":
            connection.execute(
                """
                INSERT INTO meal_items (
                    id, meal_id, catalog_food_id, food_name, amount, unit,
                    basis_type, calories, carbs, protein, fat, source
                ) VALUES (
                    'child-1', 'late-meal', 'late-food', 'Rice', 100, 'g',
                    'per_100g', 116, 25.9, 2.6, 0.3, 'user_custom'
                )
                """
            )
        else:
            connection.execute(
                """
                UPDATE meal_items
                SET meal_id = 'late-meal', catalog_food_id = 'late-food'
                WHERE id = 'child-1'
                """
            )
        return

    item_kind = case.split("_", maxsplit=1)[0]
    if operation == "insert" and item_kind == "strength":
        connection.execute(
            """
            INSERT INTO strength_exercises (
                id, session_id, catalog_exercise_id, exercise_name,
                primary_muscle, position
            ) VALUES (
                'child-1', 'late-session', 'late-exercise', 'Squat', 'legs', 1
            )
            """
        )
    elif operation == "insert":
        connection.execute(
            """
            INSERT INTO cardio_items (
                id, session_id, catalog_exercise_id, activity_name,
                duration_min, position
            ) VALUES (
                'child-1', 'late-session', 'late-exercise', 'Run', 20, 1
            )
            """
        )
    else:
        table_name = (
            "strength_exercises" if item_kind == "strength" else "cardio_items"
        )
        connection.execute(
            f"""
            UPDATE {table_name}
            SET session_id = 'late-session', catalog_exercise_id = 'late-exercise'
            WHERE id = 'child-1'
            """
        )


def _insert_late_invalid_parents(connection, case):
    if case in ("favorite", "usage"):
        _insert_food(
            connection,
            food_id="late-food",
            source="user_custom",
            owner_user_id="user-b",
            source_record_id="late-food",
        )
        return

    if case == "meal":
        _insert_meal(connection, meal_id="late-meal")
        _insert_food(
            connection,
            food_id="late-food",
            source="user_custom",
            owner_user_id="user-b",
            source_record_id="late-food",
        )
        return

    item_kind, violation_kind = case.split("_", maxsplit=1)
    _insert_session(connection, session_id="late-session")
    if violation_kind == "owner":
        _insert_exercise(
            connection,
            exercise_id="late-exercise",
            source="user_custom",
            owner_user_id="user-b",
            source_record_id="late-exercise",
            exercise_type=item_kind,
        )
    else:
        mismatched_type = "cardio" if item_kind == "strength" else "strength"
        _insert_exercise(
            connection,
            exercise_id="late-exercise",
            source_record_id="late-exercise",
            exercise_type=mismatched_type,
        )


def test_records_schema_contains_required_tables_and_fts(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")

    run_migrations(database, RECORDS_MIGRATIONS)

    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO catalog_search (
                catalog_kind, catalog_id, name, aliases, pinyin, source_tokens
            ) VALUES (
                'food', 'food-search-1', 'Chicken breast',
                'chicken poultry', 'jixiong', 'public test-foods'
            )
            """
        )

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
        search_result = connection.execute(
            """
            SELECT catalog_id
            FROM catalog_search
            WHERE catalog_search MATCH 'chicken'
            """
        ).fetchone()

    assert REQUIRED_TABLES <= tables
    assert catalog_search_sql is not None
    assert "VIRTUAL TABLE" in catalog_search_sql["sql"].upper()
    assert search_result["catalog_id"] == "food-search-1"


def test_catalog_search_supports_presegmented_chinese_alias_and_pinyin(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)

    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO catalog_search (
                catalog_kind, catalog_id, name, aliases, pinyin, source_tokens
            ) VALUES (
                'food', 'food-search-1', 'Kung pao chicken', '辣子鸡丁',
                'gongbaojiding', '宫保鸡丁 宫保 保鸡 鸡丁 辣子鸡丁 辣子 子鸡 鸡丁'
            )
            """
        )

    with database.connection() as connection:
        catalog_search_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'catalog_search'"
        ).fetchone()["sql"]
        matches = {
            query: connection.execute(
                """
                SELECT catalog_id FROM catalog_search
                WHERE catalog_search MATCH ?
                """,
                (query,),
            ).fetchone()["catalog_id"]
            for query in (
                "chicken",
                "宫保鸡丁",
                "鸡丁",
                "辣子鸡丁",
                "gongbaojiding",
                "gongbao*",
            )
        }

    assert "tokenize = 'unicode61 remove_diacritics 2'" in catalog_search_sql
    assert "prefix = '2 3 4'" in catalog_search_sql
    assert set(matches.values()) == {"food-search-1"}


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


def test_deleting_catalog_food_sets_meal_item_reference_to_null(tmp_path):
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
        _insert_food(connection)
        connection.execute(
            """
            INSERT INTO meal_items (
                id, meal_id, catalog_food_id, food_name, amount, unit,
                basis_type, calories, carbs, protein, fat, source
            ) VALUES (
                'item-1', 'meal-1', 'food-1', 'Rice', 100, 'g', 'per_100g',
                116, 25.9, 2.6, 0.3, 'public'
            )
            """
        )
        connection.execute("DELETE FROM food_catalog WHERE id = 'food-1'")

    with database.connection() as connection:
        catalog_food_id = connection.execute(
            "SELECT catalog_food_id FROM meal_items WHERE id = 'item-1'"
        ).fetchone()["catalog_food_id"]

    assert catalog_food_id is None


@pytest.mark.parametrize(
    ("item_kind", "exercise_type"),
    [("strength", "strength"), ("cardio", "cardio")],
)
def test_deleting_catalog_exercise_sets_training_reference_to_null(
    tmp_path, item_kind, exercise_type
):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    item_statements = {
        "strength": """
            INSERT INTO strength_exercises (
                id, session_id, catalog_exercise_id, exercise_name,
                primary_muscle, position
            ) VALUES ('item-1', 'session-1', 'exercise-1', 'Squat', 'legs', 1)
        """,
        "cardio": """
            INSERT INTO cardio_items (
                id, session_id, catalog_exercise_id, activity_name,
                duration_min, position
            ) VALUES ('item-1', 'session-1', 'exercise-1', 'Run', 20, 1)
        """,
    }
    table_name = "strength_exercises" if item_kind == "strength" else "cardio_items"

    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO training_sessions (
                id, user_id, log_date, title, entry_method
            ) VALUES ('session-1', 'user-a', '2026-07-01', 'Training', 'form')
            """
        )
        _insert_exercise(connection, exercise_type=exercise_type)
        connection.execute(item_statements[item_kind])
        connection.execute("DELETE FROM exercise_catalog WHERE id = 'exercise-1'")

    with database.connection() as connection:
        catalog_exercise_id = connection.execute(
            f"SELECT catalog_exercise_id FROM {table_name} WHERE id = 'item-1'"
        ).fetchone()["catalog_exercise_id"]

    assert catalog_exercise_id is None


def test_meal_items_only_link_food_visible_to_meal_owner(tmp_path):
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
        _insert_food(connection)
        _insert_food(
            connection,
            food_id="food-private-a",
            source="user_custom",
            owner_user_id="user-a",
            source_record_id="private-a",
        )
        _insert_food(
            connection,
            food_id="food-private-b",
            source="user_custom",
            owner_user_id="user-b",
            source_record_id="private-b",
        )
        for item_id, catalog_food_id in (
            ("item-public", "food-1"),
            ("item-private-a", "food-private-a"),
        ):
            connection.execute(
                """
                INSERT INTO meal_items (
                    id, meal_id, catalog_food_id, food_name, amount, unit,
                    basis_type, calories, carbs, protein, fat, source
                ) VALUES (
                    ?, 'meal-1', ?, 'Rice', 100, 'g', 'per_100g',
                    116, 25.9, 2.6, 0.3, 'user_custom'
                )
                """,
                (item_id, catalog_food_id),
            )

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO meal_items (
                    id, meal_id, catalog_food_id, food_name, amount, unit,
                    basis_type, calories, carbs, protein, fat, source
                ) VALUES (
                    'item-private-b', 'meal-1', 'food-private-b', 'Rice',
                    100, 'g', 'per_100g', 116, 25.9, 2.6, 0.3, 'user_custom'
                )
                """
            )


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
        _insert_food(connection)
        _insert_exercise(connection)

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
        "idx_profile_versions_user_id": ("user_id", "id"),
        "idx_goal_versions_user_id": ("user_id", "id"),
        "idx_target_versions_user_id": ("user_id", "id"),
        "idx_target_versions_profile": ("user_id", "profile_version_id"),
        "idx_target_versions_goal": ("user_id", "overall_goal_version_id"),
        "idx_daily_logs_target": ("user_id", "target_version_id"),
        "idx_food_public_source": ("source_name", "source_record_id"),
        "idx_food_private_source": (
            "owner_user_id",
            "source_name",
            "source_record_id",
        ),
        "idx_food_owner_name": ("owner_user_id", "name"),
        "idx_exercise_public_source": ("source_name", "source_record_id"),
        "idx_exercise_private_source": (
            "owner_user_id",
            "source_name",
            "source_record_id",
        ),
        "idx_exercise_owner_name": ("owner_user_id", "name"),
        "idx_catalog_alias_food": ("food_id",),
        "idx_catalog_alias_exercise": ("exercise_id",),
        "idx_catalog_alias_normalized": ("normalized_alias",),
        "idx_catalog_favorites_user_food": ("user_id", "food_id"),
        "idx_catalog_favorites_user_exercise": ("user_id", "exercise_id"),
        "idx_catalog_favorites_food": ("food_id",),
        "idx_catalog_favorites_exercise": ("exercise_id",),
        "idx_catalog_usage_user_food": ("user_id", "food_id"),
        "idx_catalog_usage_user_exercise": ("user_id", "exercise_id"),
        "idx_catalog_usage_food": ("food_id",),
        "idx_catalog_usage_exercise": ("exercise_id",),
        "idx_catalog_usage_recent": ("user_id", "last_used_at"),
        "idx_record_drafts_user_expiry": ("user_id", "expires_at"),
        "idx_meal_items_meal": ("meal_id",),
        "idx_meal_items_catalog": ("catalog_food_id",),
        "idx_training_sessions_user_date": ("user_id", "log_date"),
        "idx_strength_exercises_catalog": ("catalog_exercise_id",),
        "idx_cardio_items_catalog": ("catalog_exercise_id",),
    }
    required_unique_indexes = {
        "idx_profile_versions_user_id",
        "idx_goal_versions_user_id",
        "idx_target_versions_user_id",
        "idx_food_public_source",
        "idx_food_private_source",
        "idx_exercise_public_source",
        "idx_exercise_private_source",
        "idx_catalog_favorites_user_food",
        "idx_catalog_favorites_user_exercise",
        "idx_catalog_usage_user_food",
        "idx_catalog_usage_user_exercise",
    }
    removed_redundant_indexes = {
        "idx_profile_versions_user_effective",
        "idx_goal_versions_user_effective",
        "idx_target_versions_user_effective",
        "idx_meals_user_date",
        "idx_strength_exercises_session",
        "idx_strength_sets_exercise",
        "idx_cardio_items_session",
    }
    unique_constraint_columns = {
        "user_profile_versions": ("user_id", "effective_from"),
        "overall_goal_versions": ("user_id", "effective_from"),
        "daily_target_versions": ("user_id", "effective_from"),
        "daily_logs": ("user_id", "log_date"),
        "meals": ("user_id", "log_date", "position"),
        "strength_exercises": ("session_id", "position"),
        "strength_sets": ("strength_exercise_id", "set_number"),
        "cardio_items": ("session_id", "position"),
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
        index_sql = {
            row["name"]: row["sql"]
            for row in connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'index'"
            )
        }
        actual_unique_constraints = {
            table_name: {
                tuple(
                    column["name"]
                    for column in connection.execute(
                        "SELECT name FROM pragma_index_info(?)",
                        (index_row["name"],),
                    )
                )
                for index_row in connection.execute(
                    f"PRAGMA index_list('{table_name}')"
                )
                if index_row["origin"] == "u"
            }
            for table_name in unique_constraint_columns
        }

    assert actual_indexes == required_indexes
    assert all(
        index_sql[index_name].upper().startswith("CREATE UNIQUE INDEX")
        for index_name in required_unique_indexes
    )
    assert removed_redundant_indexes.isdisjoint(index_sql)
    assert all(
        expected_columns in actual_unique_constraints[table_name]
        for table_name, expected_columns in unique_constraint_columns.items()
    )


def test_records_v1_checksum_is_historical_constant():
    assert RECORDS_MIGRATIONS[0].checksum == V1_CHECKSUM


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

    assert [tuple(row) for row in applied] == [
        (1, "create_records_schema"),
        (2, "enforce_records_schema_invariants"),
    ]
    assert catalog_search_count == 1


def test_records_v1_upgrades_to_v2_without_losing_data(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    old_v1 = RECORDS_MIGRATIONS[0]

    run_migrations(database, (old_v1,))
    with database.transaction() as connection:
        _insert_food(
            connection,
            source="user_custom",
            owner_user_id="user-a",
        )
        connection.execute(
            """
            INSERT INTO catalog_search (
                rowid, catalog_kind, catalog_id, name, aliases, pinyin,
                source_tokens
            ) VALUES (
                42, 'food', 'food-1', 'Kung pao chicken', '辣子鸡丁',
                'gongbaojiding',
                '宫保鸡丁 宫保 保鸡 鸡丁 辣子鸡丁 辣子 子鸡 鸡丁'
            )
            """
        )

    run_migrations(database, RECORDS_MIGRATIONS)
    run_migrations(database, RECORDS_MIGRATIONS)

    with database.connection() as connection:
        applied = connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
        food = connection.execute(
            "SELECT owner_user_id, name FROM food_catalog WHERE id = 'food-1'"
        ).fetchone()
        search_row = connection.execute(
            """
            SELECT rowid, catalog_id FROM catalog_search
            WHERE catalog_search MATCH '宫保鸡丁'
            """
        ).fetchone()
        catalog_search_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'catalog_search'"
        ).fetchone()["sql"]

    assert [tuple(row) for row in applied] == [
        (1, "create_records_schema"),
        (2, "enforce_records_schema_invariants"),
    ]
    assert tuple(food) == ("user-a", "Rice")
    assert tuple(search_row) == (42, "food-1")
    assert "tokenize = 'unicode61 remove_diacritics 2'" in catalog_search_sql
    assert "prefix = '2 3 4'" in catalog_search_sql

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO catalog_favorites (id, user_id, food_id)
                VALUES ('favorite-1', 'user-b', 'food-1')
                """
            )


@pytest.mark.parametrize(
    "violation",
    [
        "favorite_owner",
        "usage_owner",
        "meal_owner",
        "strength_owner",
        "strength_subtype",
        "cardio_owner",
        "cardio_subtype",
        "json_array_profile",
        "json_object_food",
        "json_array_strength",
    ],
)
def test_records_v2_rejects_invalid_v1_data_atomically(tmp_path, violation):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, (RECORDS_MIGRATIONS[0],))

    with database.transaction() as connection:
        table_name, row_id = _seed_v1_upgrade_violation(connection, violation)

    with pytest.raises(sqlite3.IntegrityError):
        run_migrations(database, RECORDS_MIGRATIONS)

    with database.connection() as connection:
        applied = connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
        trigger_count = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger'"
        ).fetchone()[0]
        migration_artifacts = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE name IN ('records_v2_migration_guard', 'catalog_search_v2')
            """
        ).fetchall()
        catalog_search_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'catalog_search'"
        ).fetchone()[0]
        invalid_row_count = connection.execute(
            f"SELECT COUNT(*) FROM {table_name} WHERE id = ?", (row_id,)
        ).fetchone()[0]

    assert [tuple(row) for row in applied] == [(1, "create_records_schema")]
    assert trigger_count == 0
    assert migration_artifacts == []
    assert "remove_diacritics" not in catalog_search_sql
    assert invalid_row_count == 1


def test_version_links_reject_cross_user_references(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)

    with database.transaction() as connection:
        _insert_profile(connection)
        _insert_goal(connection)
        _insert_target(connection)

    invalid_inserts = [
        (
            """
            INSERT INTO daily_target_versions (
                id, user_id, profile_version_id, calories, carbs, protein,
                fat, source, effective_from
            ) VALUES (
                'target-cross-profile', 'user-b', 'profile-1',
                2000, 200, 100, 60, 'manual', '2026-07-02'
            )
            """
        ),
        (
            """
            INSERT INTO daily_target_versions (
                id, user_id, overall_goal_version_id, calories, carbs,
                protein, fat, source, effective_from
            ) VALUES (
                'target-cross-goal', 'user-b', 'goal-1',
                2000, 200, 100, 60, 'manual', '2026-07-03'
            )
            """
        ),
        (
            """
            INSERT INTO daily_logs (
                id, user_id, log_date, target_version_id
            ) VALUES (
                'log-cross-target', 'user-b', '2026-07-01', 'target-1'
            )
            """
        ),
    ]

    for statement in invalid_inserts:
        with pytest.raises(sqlite3.IntegrityError):
            with database.transaction() as connection:
                connection.execute(statement)


def test_referenced_version_history_cannot_be_deleted(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)

    with database.transaction() as connection:
        _insert_profile(connection)
        _insert_goal(connection)
        _insert_target(
            connection,
            profile_id="profile-1",
            goal_id="goal-1",
        )
        connection.execute(
            """
            INSERT INTO daily_logs (
                id, user_id, log_date, target_version_id
            ) VALUES ('log-1', 'user-a', '2026-07-01', 'target-1')
            """
        )

    for statement in (
        "DELETE FROM user_profile_versions WHERE id = 'profile-1'",
        "DELETE FROM overall_goal_versions WHERE id = 'goal-1'",
        "DELETE FROM daily_target_versions WHERE id = 'target-1'",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            with database.transaction() as connection:
                connection.execute(statement)

    with database.connection() as connection:
        target_foreign_keys = sorted(
            (row["from"], row["to"], row["on_delete"])
            for row in connection.execute(
                "PRAGMA foreign_key_list('daily_target_versions')"
            )
        )
        log_foreign_keys = sorted(
            (row["from"], row["to"], row["on_delete"])
            for row in connection.execute("PRAGMA foreign_key_list('daily_logs')")
        )

    assert target_foreign_keys == [
        ("overall_goal_version_id", "id", "RESTRICT"),
        ("profile_version_id", "id", "RESTRICT"),
        ("user_id", "user_id", "RESTRICT"),
        ("user_id", "user_id", "RESTRICT"),
    ]
    assert log_foreign_keys == [
        ("target_version_id", "id", "RESTRICT"),
        ("user_id", "user_id", "RESTRICT"),
    ]


@pytest.mark.parametrize("catalog_kind", ["food", "exercise"])
@pytest.mark.parametrize(
    ("source", "owner_user_id"),
    [
        ("public", "user-a"),
        ("user_custom", None),
        ("agent_estimate", None),
        ("legacy_import", None),
    ],
)
def test_catalog_source_requires_matching_owner_partition(
    tmp_path, catalog_kind, source, owner_user_id
):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            if catalog_kind == "food":
                _insert_food(
                    connection,
                    source=source,
                    owner_user_id=owner_user_id,
                )
            else:
                _insert_exercise(
                    connection,
                    source=source,
                    owner_user_id=owner_user_id,
                )


@pytest.mark.parametrize("catalog_kind", ["food", "exercise"])
def test_private_catalog_source_identity_is_unique_per_owner(
    tmp_path, catalog_kind
):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    insert_record = _insert_food if catalog_kind == "food" else _insert_exercise
    second_id_kwargs = (
        {"food_id": "food-2"}
        if catalog_kind == "food"
        else {"exercise_id": "exercise-2"}
    )

    with database.transaction() as connection:
        insert_record(
            connection,
            source="user_custom",
            owner_user_id="user-a",
            source_name="private-source",
            source_record_id="shared-id",
        )
        insert_record(
            connection,
            **second_id_kwargs,
            source="user_custom",
            owner_user_id="user-b",
            source_name="private-source",
            source_record_id="shared-id",
        )

    duplicate_id = "food-3" if catalog_kind == "food" else "exercise-3"
    duplicate_kwargs = (
        {"food_id": duplicate_id}
        if catalog_kind == "food"
        else {"exercise_id": duplicate_id}
    )
    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            insert_record(
                connection,
                **duplicate_kwargs,
                source="user_custom",
                owner_user_id="user-a",
                source_name="private-source",
                source_record_id="shared-id",
            )


@pytest.mark.parametrize("operation", ["insert", "update"])
@pytest.mark.parametrize(
    "case",
    [
        "favorite",
        "usage",
        "meal",
        "strength_owner",
        "strength_subtype",
        "cardio_owner",
        "cardio_subtype",
    ],
)
def test_deferred_foreign_keys_cannot_bypass_catalog_invariants(
    tmp_path, case, operation
):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)

    if operation == "update":
        with database.transaction() as connection:
            _seed_valid_deferred_child(connection, case)

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute("PRAGMA defer_foreign_keys = ON")
            _write_deferred_child(connection, case, operation)
            _insert_late_invalid_parents(connection, case)


@pytest.mark.parametrize("table_name", ["catalog_favorites", "catalog_usage"])
@pytest.mark.parametrize("target_column", ["food_id", "exercise_id"])
def test_catalog_user_relations_reject_nonexistent_targets(
    tmp_path, table_name, target_column
):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                f"""
                INSERT INTO {table_name} (id, user_id, {target_column})
                VALUES ('relation-1', 'user-a', 'missing-target')
                """
            )


@pytest.mark.parametrize("table_name", ["catalog_favorites", "catalog_usage"])
@pytest.mark.parametrize("catalog_kind", ["food", "exercise"])
def test_catalog_user_relations_only_link_visible_catalog_rows(
    tmp_path, table_name, catalog_kind
):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    target_column = "food_id" if catalog_kind == "food" else "exercise_id"
    insert_record = _insert_food if catalog_kind == "food" else _insert_exercise

    with database.transaction() as connection:
        insert_record(connection)
        insert_record(
            connection,
            **{f"{catalog_kind}_id": f"{catalog_kind}-private-a"},
            source="user_custom",
            owner_user_id="user-a",
            source_record_id="private-a",
        )
        insert_record(
            connection,
            **{f"{catalog_kind}_id": f"{catalog_kind}-private-b"},
            source="user_custom",
            owner_user_id="user-b",
            source_record_id="private-b",
        )
        connection.execute(
            f"""
            INSERT INTO {table_name} (id, user_id, {target_column})
            VALUES ('relation-public', 'user-a', '{catalog_kind}-1')
            """
        )
        connection.execute(
            f"""
            INSERT INTO {table_name} (id, user_id, {target_column})
            VALUES (
                'relation-private-a', 'user-a', '{catalog_kind}-private-a'
            )
            """
        )

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                f"""
                INSERT INTO {table_name} (id, user_id, {target_column})
                VALUES (
                    'relation-private-b', 'user-a',
                    '{catalog_kind}-private-b'
                )
                """
            )


@pytest.mark.parametrize("table_name", ["catalog_favorites", "catalog_usage"])
@pytest.mark.parametrize("catalog_kind", ["food", "exercise"])
def test_catalog_user_relation_updates_recheck_visibility(
    tmp_path, table_name, catalog_kind
):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    target_column = "food_id" if catalog_kind == "food" else "exercise_id"
    insert_record = _insert_food if catalog_kind == "food" else _insert_exercise

    with database.transaction() as connection:
        insert_record(connection)
        for owner in ("a", "b"):
            insert_record(
                connection,
                **{f"{catalog_kind}_id": f"{catalog_kind}-private-{owner}"},
                source="user_custom",
                owner_user_id=f"user-{owner}",
                source_record_id=f"private-{owner}",
            )
        connection.execute(
            f"""
            INSERT INTO {table_name} (id, user_id, {target_column})
            VALUES ('relation-1', 'user-a', '{catalog_kind}-1')
            """
        )

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                f"""
                UPDATE {table_name}
                SET {target_column} = '{catalog_kind}-private-b'
                WHERE id = 'relation-1'
                """
            )

    with database.transaction() as connection:
        connection.execute(
            f"""
            UPDATE {table_name}
            SET {target_column} = '{catalog_kind}-private-a'
            WHERE id = 'relation-1'
            """
        )

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                f"""
                UPDATE {table_name} SET user_id = 'user-b'
                WHERE id = 'relation-1'
                """
            )


@pytest.mark.parametrize("table_name", ["catalog_favorites", "catalog_usage"])
def test_catalog_user_relations_require_exactly_one_target(tmp_path, table_name):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)

    with database.transaction() as connection:
        _insert_food(connection)
        _insert_exercise(connection)

    for relation_id, food_id, exercise_id in (
        ("relation-both", "food-1", "exercise-1"),
        ("relation-neither", None, None),
    ):
        with pytest.raises(sqlite3.IntegrityError):
            with database.transaction() as connection:
                connection.execute(
                    f"""
                    INSERT INTO {table_name} (
                        id, user_id, food_id, exercise_id
                    ) VALUES (?, 'user-a', ?, ?)
                    """,
                    (relation_id, food_id, exercise_id),
                )


@pytest.mark.parametrize("catalog_kind", ["food", "exercise"])
def test_deleting_catalog_row_cascades_user_relations(tmp_path, catalog_kind):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    target_column = "food_id" if catalog_kind == "food" else "exercise_id"
    catalog_table = "food_catalog" if catalog_kind == "food" else "exercise_catalog"
    catalog_id = "food-1" if catalog_kind == "food" else "exercise-1"

    with database.transaction() as connection:
        if catalog_kind == "food":
            _insert_food(connection)
        else:
            _insert_exercise(connection)
        connection.execute(
            f"""
            INSERT INTO catalog_favorites (id, user_id, {target_column})
            VALUES ('favorite-1', 'user-a', ?)
            """,
            (catalog_id,),
        )
        connection.execute(
            f"""
            INSERT INTO catalog_usage (id, user_id, {target_column})
            VALUES ('usage-1', 'user-a', ?)
            """,
            (catalog_id,),
        )
        connection.execute(
            f"DELETE FROM {catalog_table} WHERE id = ?", (catalog_id,)
        )

    with database.connection() as connection:
        relation_counts = [
            connection.execute(
                f"SELECT COUNT(*) AS count FROM {table_name}"
            ).fetchone()["count"]
            for table_name in ("catalog_favorites", "catalog_usage")
        ]
        foreign_key_actions = {
            table_name: {
                (row["from"], row["on_delete"])
                for row in connection.execute(
                    f"PRAGMA foreign_key_list('{table_name}')"
                )
            }
            for table_name in ("catalog_favorites", "catalog_usage")
        }

    assert relation_counts == [0, 0]
    assert foreign_key_actions == {
        "catalog_favorites": {
            ("food_id", "CASCADE"),
            ("exercise_id", "CASCADE"),
        },
        "catalog_usage": {
            ("food_id", "CASCADE"),
            ("exercise_id", "CASCADE"),
        },
    }


@pytest.mark.parametrize("item_kind", ["strength", "cardio"])
def test_training_item_position_is_unique_within_session(tmp_path, item_kind):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    statements = {
        "strength": """
            INSERT INTO strength_exercises (
                id, session_id, exercise_name, primary_muscle, position
            ) VALUES (?, 'session-1', 'Squat', 'legs', 1)
        """,
        "cardio": """
            INSERT INTO cardio_items (
                id, session_id, activity_name, duration_min, position
            ) VALUES (?, 'session-1', 'Running', 20, 1)
        """,
    }

    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO training_sessions (
                id, user_id, log_date, title, entry_method
            ) VALUES ('session-1', 'user-a', '2026-07-01', 'Training', 'form')
            """
        )
        connection.execute(statements[item_kind], ("item-1",))

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(statements[item_kind], ("item-2",))


@pytest.mark.parametrize(
    ("item_kind", "catalog_type", "mismatched_type"),
    [
        ("strength", "strength", "cardio"),
        ("cardio", "cardio", "strength"),
    ],
)
def test_training_items_require_visible_matching_catalog_subtype(
    tmp_path, item_kind, catalog_type, mismatched_type
):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    item_statements = {
        "strength": """
            INSERT INTO strength_exercises (
                id, session_id, catalog_exercise_id, exercise_name,
                primary_muscle, position
            ) VALUES (?, 'session-1', ?, 'Exercise', 'legs', ?)
        """,
        "cardio": """
            INSERT INTO cardio_items (
                id, session_id, catalog_exercise_id, activity_name,
                duration_min, position
            ) VALUES (?, 'session-1', ?, 'Exercise', 20, ?)
        """,
    }

    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO training_sessions (
                id, user_id, log_date, title, entry_method
            ) VALUES ('session-1', 'user-a', '2026-07-01', 'Training', 'form')
            """
        )
        _insert_exercise(connection, exercise_type=catalog_type)
        _insert_exercise(
            connection,
            exercise_id="exercise-private-a",
            source="user_custom",
            owner_user_id="user-a",
            source_record_id="private-a",
            exercise_type=catalog_type,
        )
        _insert_exercise(
            connection,
            exercise_id="exercise-private-b",
            source="user_custom",
            owner_user_id="user-b",
            source_record_id="private-b",
            exercise_type=catalog_type,
        )
        _insert_exercise(
            connection,
            exercise_id="exercise-mismatched",
            source_record_id="mismatched",
            exercise_type=mismatched_type,
        )
        connection.execute(
            item_statements[item_kind], ("item-public", "exercise-1", 1)
        )
        connection.execute(
            item_statements[item_kind],
            ("item-private-a", "exercise-private-a", 2),
        )

    for item_id, exercise_id, position in (
        ("item-private-b", "exercise-private-b", 3),
        ("item-mismatched", "exercise-mismatched", 4),
    ):
        with pytest.raises(sqlite3.IntegrityError):
            with database.transaction() as connection:
                connection.execute(
                    item_statements[item_kind],
                    (item_id, exercise_id, position),
                )


def test_meal_item_updates_recheck_catalog_visibility(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)

    with database.transaction() as connection:
        for meal_id, user_id, position in (
            ("meal-a", "user-a", 1),
            ("meal-b", "user-b", 2),
        ):
            connection.execute(
                """
                INSERT INTO meals (
                    id, user_id, log_date, name, meal_type, position,
                    entry_method
                ) VALUES (?, ?, '2026-07-19', 'Lunch', 'lunch', ?, 'form')
                """,
                (meal_id, user_id, position),
            )
        _insert_food(connection)
        for owner in ("a", "b"):
            _insert_food(
                connection,
                food_id=f"food-private-{owner}",
                source="user_custom",
                owner_user_id=f"user-{owner}",
                source_record_id=f"private-{owner}",
            )
        connection.execute(
            """
            INSERT INTO meal_items (
                id, meal_id, catalog_food_id, food_name, amount, unit,
                basis_type, calories, carbs, protein, fat, source
            ) VALUES (
                'item-1', 'meal-a', 'food-1', 'Rice', 100, 'g', 'per_100g',
                116, 25.9, 2.6, 0.3, 'user_custom'
            )
            """
        )

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                """
                UPDATE meal_items SET catalog_food_id = 'food-private-b'
                WHERE id = 'item-1'
                """
            )

    with database.transaction() as connection:
        connection.execute(
            """
            UPDATE meal_items SET catalog_food_id = 'food-private-a'
            WHERE id = 'item-1'
            """
        )

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                "UPDATE meal_items SET meal_id = 'meal-b' WHERE id = 'item-1'"
            )


@pytest.mark.parametrize(
    ("item_kind", "catalog_type", "mismatched_type"),
    [
        ("strength", "strength", "cardio"),
        ("cardio", "cardio", "strength"),
    ],
)
def test_training_item_updates_recheck_visibility_and_subtype(
    tmp_path, item_kind, catalog_type, mismatched_type
):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    insert_item = {
        "strength": """
            INSERT INTO strength_exercises (
                id, session_id, catalog_exercise_id, exercise_name,
                primary_muscle, position
            ) VALUES ('item-1', 'session-a', 'exercise-1', 'Exercise', 'legs', 1)
        """,
        "cardio": """
            INSERT INTO cardio_items (
                id, session_id, catalog_exercise_id, activity_name,
                duration_min, position
            ) VALUES ('item-1', 'session-a', 'exercise-1', 'Exercise', 20, 1)
        """,
    }
    table_name = "strength_exercises" if item_kind == "strength" else "cardio_items"

    with database.transaction() as connection:
        for session_id, user_id in (("session-a", "user-a"), ("session-b", "user-b")):
            connection.execute(
                """
                INSERT INTO training_sessions (
                    id, user_id, log_date, title, entry_method
                ) VALUES (?, ?, '2026-07-01', 'Training', 'form')
                """,
                (session_id, user_id),
            )
        _insert_exercise(connection, exercise_type=catalog_type)
        for owner in ("a", "b"):
            _insert_exercise(
                connection,
                exercise_id=f"exercise-private-{owner}",
                source="user_custom",
                owner_user_id=f"user-{owner}",
                source_record_id=f"private-{owner}",
                exercise_type=catalog_type,
            )
        _insert_exercise(
            connection,
            exercise_id="exercise-mismatched",
            source_record_id="mismatched",
            exercise_type=mismatched_type,
        )
        connection.execute(insert_item[item_kind])

    for exercise_id in ("exercise-private-b", "exercise-mismatched"):
        with pytest.raises(sqlite3.IntegrityError):
            with database.transaction() as connection:
                connection.execute(
                    f"""
                    UPDATE {table_name} SET catalog_exercise_id = ?
                    WHERE id = 'item-1'
                    """,
                    (exercise_id,),
                )

    with database.transaction() as connection:
        connection.execute(
            f"""
            UPDATE {table_name} SET catalog_exercise_id = 'exercise-private-a'
            WHERE id = 'item-1'
            """
        )

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(
                f"""
                UPDATE {table_name} SET session_id = 'session-b'
                WHERE id = 'item-1'
                """
            )


def test_catalog_partition_and_exercise_subtype_are_immutable(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)

    with database.transaction() as connection:
        _insert_food(
            connection,
            source="user_custom",
            owner_user_id="user-a",
        )
        _insert_exercise(
            connection,
            source="user_custom",
            owner_user_id="user-a",
        )
        connection.execute(
            """
            INSERT INTO catalog_favorites (id, user_id, food_id)
            VALUES ('favorite-1', 'user-a', 'food-1')
            """
        )
        connection.execute(
            """
            INSERT INTO training_sessions (
                id, user_id, log_date, title, entry_method
            ) VALUES ('session-1', 'user-a', '2026-07-01', 'Training', 'form')
            """
        )
        connection.execute(
            """
            INSERT INTO strength_exercises (
                id, session_id, catalog_exercise_id, exercise_name,
                primary_muscle, position
            ) VALUES (
                'strength-1', 'session-1', 'exercise-1', 'Squat', 'legs', 1
            )
            """
        )

    invalid_updates = (
        "UPDATE food_catalog SET owner_user_id = 'user-b' WHERE id = 'food-1'",
        "UPDATE food_catalog SET source = 'agent_estimate' WHERE id = 'food-1'",
        "UPDATE exercise_catalog SET owner_user_id = 'user-b' WHERE id = 'exercise-1'",
        "UPDATE exercise_catalog SET source = 'agent_estimate' WHERE id = 'exercise-1'",
        "UPDATE exercise_catalog SET exercise_type = 'cardio' WHERE id = 'exercise-1'",
    )
    for statement in invalid_updates:
        with pytest.raises(sqlite3.IntegrityError):
            with database.transaction() as connection:
                connection.execute(statement)

    with database.transaction() as connection:
        connection.execute("UPDATE food_catalog SET name = 'Rice 2' WHERE id = 'food-1'")
        connection.execute(
            "UPDATE exercise_catalog SET name = 'Squat 2' WHERE id = 'exercise-1'"
        )


def test_meal_and_training_session_owners_are_immutable(tmp_path):
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
            INSERT INTO training_sessions (
                id, user_id, log_date, title, entry_method
            ) VALUES ('session-1', 'user-a', '2026-07-01', 'Training', 'form')
            """
        )

    for statement in (
        "UPDATE meals SET user_id = 'user-b' WHERE id = 'meal-1'",
        "UPDATE training_sessions SET user_id = 'user-b' WHERE id = 'session-1'",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            with database.transaction() as connection:
                connection.execute(statement)


def test_json_columns_declare_array_or_object_shapes(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    expected_shapes = {
        "data_migrations": {"details_json": "object"},
        "user_profile_versions": {"safety_conditions_json": "array"},
        "daily_target_versions": {"rationale_json": "object"},
        "food_catalog": {"provenance_json": "object"},
        "exercise_catalog": {
            "secondary_muscles_json": "array",
            "provenance_json": "object",
        },
        "record_drafts": {
            "payload_json": "object",
            "agent_metadata_json": "object",
        },
        "meal_items": {
            "uncertainty_json": "object",
            "assumptions_json": "array",
            "provenance_json": "object",
        },
        "training_sessions": {"estimate_json": "object"},
        "strength_exercises": {
            "secondary_muscles_json": "array",
            "estimate_json": "object",
            "provenance_json": "object",
        },
        "cardio_items": {
            "estimate_json": "object",
            "provenance_json": "object",
        },
        "idempotency_keys": {"response_json": "object"},
        "catalog_imports": {"details_json": "object"},
    }

    with database.connection() as connection:
        trigger_sql = {
            table_name: [
                row["sql"]
                for row in connection.execute(
                    """
                    SELECT sql FROM sqlite_master
                    WHERE type = 'trigger'
                      AND tbl_name = ?
                      AND name LIKE '%_json_shape_%'
                    ORDER BY name
                    """,
                    (table_name,),
                )
            ]
            for table_name in expected_shapes
        }

    for table_name, columns in expected_shapes.items():
        assert len(trigger_sql[table_name]) == 2
        combined_sql = "\n".join(trigger_sql[table_name])
        for column_name, expected_shape in columns.items():
            assert (
                f"json_type(NEW.{column_name}) <> '{expected_shape}'"
                in combined_sql
            )


@pytest.mark.parametrize(
    "statement",
    [
        """
        INSERT INTO data_migrations (
            migration_key, checksum, status, details_json
        ) VALUES ('migration-1', 'checksum', 'running', '[]')
        """,
        """
        INSERT INTO user_profile_versions (
            id, user_id, age, height_cm, weight_kg, energy_parameter,
            activity_level, safety_conditions_json, effective_from
        ) VALUES (
            'profile-1', 'user-a', 30, 175, 70, 'neutral', 'moderate', '{}',
            '2026-07-01'
        )
        """,
        """
        INSERT INTO record_drafts (
            id, user_id, kind, schema_version, payload_json, expires_at
        ) VALUES (
            'draft-1', 'user-a', 'meal', 1, '[]', '2026-08-19T00:00:00Z'
        )
        """,
        """
        INSERT INTO idempotency_keys (
            user_id, operation, idempotency_key, response_json
        ) VALUES ('user-a', 'create-meal', 'key-1', '[]')
        """,
    ],
)
def test_json_columns_reject_the_wrong_shape(tmp_path, statement):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(statement)


@pytest.mark.parametrize(
    ("insert_statement", "update_statement"),
    [
        (
            """
            INSERT INTO data_migrations (migration_key, checksum, status)
            VALUES ('migration-1', 'checksum', 'running')
            """,
            """
            UPDATE data_migrations SET details_json = '[]'
            WHERE migration_key = 'migration-1'
            """,
        ),
        (
            """
            INSERT INTO user_profile_versions (
                id, user_id, age, height_cm, weight_kg, energy_parameter,
                activity_level, effective_from
            ) VALUES (
                'profile-1', 'user-a', 30, 175, 70, 'neutral', 'moderate',
                '2026-07-01'
            )
            """,
            """
            UPDATE user_profile_versions SET safety_conditions_json = '{}'
            WHERE id = 'profile-1'
            """,
        ),
        (
            """
            INSERT INTO record_drafts (
                id, user_id, kind, schema_version, payload_json, expires_at
            ) VALUES (
                'draft-1', 'user-a', 'meal', 1, '{}',
                '2026-08-19T00:00:00Z'
            )
            """,
            "UPDATE record_drafts SET payload_json = '[]' WHERE id = 'draft-1'",
        ),
        (
            """
            INSERT INTO idempotency_keys (
                user_id, operation, idempotency_key, response_json
            ) VALUES ('user-a', 'create-meal', 'key-1', '{}')
            """,
            "UPDATE idempotency_keys SET response_json = '[]' WHERE id = 1",
        ),
    ],
)
def test_json_column_updates_reject_the_wrong_shape(
    tmp_path, insert_statement, update_statement
):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)

    with database.transaction() as connection:
        connection.execute(insert_statement)

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            connection.execute(update_statement)


def test_json_columns_accept_declared_shapes_and_valid_defaults(tmp_path):
    database = SQLiteDatabase(tmp_path / "records.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)

    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO data_migrations (migration_key, checksum, status)
            VALUES ('migration-1', 'checksum', 'running')
            """
        )
        _insert_profile(connection)
        connection.execute(
            """
            INSERT INTO record_drafts (
                id, user_id, kind, schema_version, payload_json,
                agent_metadata_json, expires_at
            ) VALUES (
                'draft-1', 'user-a', 'meal', 1, '{"items": []}',
                '{"model": "test"}', '2026-08-19T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO idempotency_keys (
                user_id, operation, idempotency_key, response_json
            ) VALUES ('user-a', 'create-meal', 'key-1', '{"id": "meal-1"}')
            """
        )

    with database.connection() as connection:
        assert connection.execute(
            "SELECT json_type(details_json) FROM data_migrations"
        ).fetchone()[0] == "object"
        assert connection.execute(
            "SELECT json_type(safety_conditions_json) FROM user_profile_versions"
        ).fetchone()[0] == "array"
