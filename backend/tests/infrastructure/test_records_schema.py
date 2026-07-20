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
):
    connection.execute(
        """
        INSERT INTO exercise_catalog (
            id, owner_user_id, source, source_name, source_record_id, name,
            exercise_type, primary_muscle
        ) VALUES (
            ?, ?, ?, ?, ?, 'Squat', 'strength', 'legs'
        )
        """,
        (exercise_id, owner_user_id, source, source_name, source_record_id),
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
