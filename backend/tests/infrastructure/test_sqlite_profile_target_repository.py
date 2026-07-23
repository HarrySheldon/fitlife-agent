from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest

from backend.application.ports.profile_target_repository import (
    GoalVersionInput,
    ProfileTargetRepositoryError,
    ProfileVersionInput,
    TargetVersionInput,
)
from backend.infrastructure.repositories.sqlite_profile_target_repository import (
    SQLiteProfileTargetRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


def _database(tmp_path) -> SQLiteDatabase:
    database = SQLiteDatabase(tmp_path / "profile-targets.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    return database


class _SnapshotProbeConnection:
    def __init__(self, connection, database) -> None:
        self._connection = connection
        self._database = database

    def execute(self, statement, parameters=()):
        cursor = self._connection.execute(statement, parameters)
        callback = self._database.after_profile_read
        if callback is not None and "FROM user_profile_versions" in statement:
            self._database.after_profile_read = None
            callback()
        return cursor

    def __getattr__(self, name):
        return getattr(self._connection, name)


class _SnapshotProbeDatabase(SQLiteDatabase):
    def __init__(self, path) -> None:
        super().__init__(path)
        self.after_profile_read = None

    @contextmanager
    def connection(self):
        with super().connection() as connection:
            yield _SnapshotProbeConnection(connection, self)


def _profile(effective_from: str, *, weight_kg: float = 70) -> ProfileVersionInput:
    return ProfileVersionInput(
        age=30,
        height_cm=175,
        weight_kg=weight_kg,
        energy_parameter="male",
        activity_level="moderate",
        auto_target_disabled=False,
        safety_conditions=(),
        effective_from=effective_from,
    )


def test_repository_appends_profile_versions_and_reads_latest_by_effective_from(tmp_path):
    repository = SQLiteProfileTargetRepository(
        _database(tmp_path),
        clock=lambda: datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc),
    )

    latest = repository.append_profile("user-a", _profile("2026-07-02", weight_kg=69))
    earlier = repository.append_profile("user-a", _profile("2026-07-01"))

    assert repository.get_latest_profile("user-a") == latest
    assert earlier.id != latest.id
    assert earlier.created_at == "2026-07-22T08:00:00Z"


def test_append_profile_if_changed_is_atomic_under_concurrent_identical_updates(tmp_path):
    database = _database(tmp_path)

    def append(index):
        return SQLiteProfileTargetRepository(database).append_profile_if_changed(
            "user-a",
            _profile(f"2026-07-22T08:00:0{index}Z"),
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(append, range(4)))

    assert results == [results[0]] * 4
    with database.connection() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM user_profile_versions WHERE user_id = ?",
            ("user-a",),
        ).fetchone()["count"]
    assert count == 1


def test_append_goal_if_changed_is_atomic_under_concurrent_identical_updates(tmp_path):
    database = _database(tmp_path)

    def append(index):
        return SQLiteProfileTargetRepository(database).append_goal_if_changed(
            "user-a",
            GoalVersionInput(
                goal="maintenance",
                effective_from=f"2026-07-22T08:00:0{index}Z",
            ),
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(append, range(4)))

    assert results == [results[0]] * 4
    with database.connection() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM overall_goal_versions WHERE user_id = ?",
            ("user-a",),
        ).fetchone()["count"]
    assert count == 1


def test_setup_reads_latest_profile_and_goal_for_only_the_requested_user(tmp_path):
    repository = SQLiteProfileTargetRepository(_database(tmp_path))
    profile_a = repository.append_profile("user-a", _profile("2026-07-01"))
    goal_a = repository.append_goal(
        "user-a", GoalVersionInput(goal="fat_loss", effective_from="2026-07-01")
    )
    repository.append_profile("user-b", _profile("2026-07-03", weight_kg=90))
    repository.append_goal(
        "user-b", GoalVersionInput(goal="muscle_gain", effective_from="2026-07-03")
    )

    setup = repository.get_setup("user-a")

    assert setup.profile == profile_a
    assert setup.goal == goal_a
    assert setup.target is None
    assert repository.get_latest_profile("missing-user") is None


def test_get_setup_reads_profile_goal_and_target_from_one_sqlite_snapshot(tmp_path):
    database = _SnapshotProbeDatabase(tmp_path / "profile-targets.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    repository = SQLiteProfileTargetRepository(database)
    original = repository.bootstrap(
        "user-a",
        _profile("2026-07-01"),
        GoalVersionInput(goal="maintenance", effective_from="2026-07-01"),
    )
    original_target = repository.append_target(
        "user-a", _target(original.profile.id, original.goal.id, "2026-07-01")
    )
    writer = SQLiteProfileTargetRepository(SQLiteDatabase(database.path))

    def append_new_setup() -> None:
        profile = writer.append_profile(
            "user-a", _profile("2026-07-03", weight_kg=68)
        )
        goal = writer.append_goal(
            "user-a",
            GoalVersionInput(goal="fat_loss", effective_from="2026-07-03"),
        )
        writer.append_target(
            "user-a", _target(profile.id, goal.id, "2026-07-03")
        )

    database.after_profile_read = append_new_setup

    setup = repository.get_setup("user-a")

    assert setup.profile == original.profile
    assert setup.goal == original.goal
    assert setup.target == original_target


def test_repository_appends_targets_and_lists_newest_effective_version_first(tmp_path):
    repository = SQLiteProfileTargetRepository(_database(tmp_path))
    profile = repository.append_profile("user-a", _profile("2026-07-01"))
    goal = repository.append_goal(
        "user-a", GoalVersionInput(goal="maintenance", effective_from="2026-07-01")
    )
    first = repository.append_target(
        "user-a",
        TargetVersionInput(
            profile_version_id=profile.id,
            overall_goal_version_id=goal.id,
            calories=2200,
            carbs=280,
            protein=112,
            fat=70,
            source="deterministic_calculation",
            formula_version="mifflin_st_jeor_v1",
            rationale={"goal": "maintenance"},
            effective_from="2026-07-01",
        ),
    )
    latest = repository.append_target(
        "user-a",
        TargetVersionInput(
            profile_version_id=profile.id,
            overall_goal_version_id=goal.id,
            calories=2100,
            carbs=250,
            protein=120,
            fat=68,
            source="manual",
            formula_version=None,
            rationale={"confirmed_warnings": []},
            effective_from="2026-07-02",
        ),
    )

    assert repository.get_latest_target("user-a") == latest
    assert repository.list_targets("user-a") == (latest, first)
    assert repository.get_setup("user-a").target == latest


def test_target_cannot_reference_another_users_profile_or_goal(tmp_path):
    repository = SQLiteProfileTargetRepository(_database(tmp_path))
    profile = repository.append_profile("user-a", _profile("2026-07-01"))
    goal = repository.append_goal(
        "user-a", GoalVersionInput(goal="maintenance", effective_from="2026-07-01")
    )

    with pytest.raises(sqlite3.IntegrityError):
        repository.append_target(
            "user-b",
            TargetVersionInput(
                profile_version_id=profile.id,
                overall_goal_version_id=goal.id,
                calories=2000,
                carbs=250,
                protein=100,
                fat=67,
                source="manual",
                formula_version=None,
                rationale={},
                effective_from="2026-07-01",
            ),
        )

    assert repository.get_latest_target("user-a") is None
    assert repository.get_latest_target("user-b") is None


def test_bootstrap_creates_profile_and_goal_atomically(tmp_path):
    repository = SQLiteProfileTargetRepository(_database(tmp_path))

    setup = repository.bootstrap(
        "user-a",
        _profile("2026-07-01"),
        GoalVersionInput(goal="fat_loss", effective_from="2026-07-01"),
    )

    assert setup.profile == repository.get_latest_profile("user-a")
    assert setup.goal == repository.get_latest_goal("user-a")
    assert setup.target is None


def test_bootstrap_rolls_back_profile_when_goal_insert_is_invalid(tmp_path):
    repository = SQLiteProfileTargetRepository(_database(tmp_path))

    with pytest.raises(sqlite3.IntegrityError):
        repository.bootstrap(
            "user-a",
            _profile("2026-07-01"),
            GoalVersionInput(goal="unsupported", effective_from="2026-07-01"),
        )

    assert repository.get_latest_profile("user-a") is None
    assert repository.get_latest_goal("user-a") is None


def _target(profile_id: str, goal_id: str, effective_from: str = "2026-07-02"):
    return TargetVersionInput(
        profile_version_id=profile_id,
        overall_goal_version_id=goal_id,
        calories=2100,
        carbs=250,
        protein=120,
        fat=68,
        source="manual",
        formula_version=None,
        rationale={"confirmed_warnings": []},
        effective_from=effective_from,
    )


def test_confirm_target_once_replays_same_response_and_rejects_fingerprint_conflict(tmp_path):
    repository = SQLiteProfileTargetRepository(_database(tmp_path))
    setup = repository.bootstrap(
        "user-a",
        _profile("2026-07-01"),
        GoalVersionInput(goal="maintenance", effective_from="2026-07-01"),
    )
    target = _target(setup.profile.id, setup.goal.id)

    first = repository.confirm_target_once("user-a", "key-1", "fingerprint-a", target)
    replay = repository.confirm_target_once("user-a", "key-1", "fingerprint-a", target)

    assert replay == first
    assert repository.list_targets("user-a") == (first,)
    with pytest.raises(ProfileTargetRepositoryError) as raised:
        repository.confirm_target_once("user-a", "key-1", "fingerprint-b", target)
    assert raised.value.code == "IDEMPOTENCY_KEY_REUSED"
    assert repository.list_targets("user-a") == (first,)


def test_confirm_target_once_is_atomic_under_concurrent_retries(tmp_path):
    database = _database(tmp_path)
    setup_repository = SQLiteProfileTargetRepository(database)
    setup = setup_repository.bootstrap(
        "user-a",
        _profile("2026-07-01"),
        GoalVersionInput(goal="maintenance", effective_from="2026-07-01"),
    )
    target = _target(setup.profile.id, setup.goal.id)

    def confirm():
        return SQLiteProfileTargetRepository(database).confirm_target_once(
            "user-a", "concurrent-key", "same-fingerprint", target
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: confirm(), range(4)))

    assert results == [results[0]] * 4
    assert setup_repository.list_targets("user-a") == (results[0],)


def test_confirm_target_replays_before_freshness_check_and_tracks_projection(tmp_path):
    repository = SQLiteProfileTargetRepository(_database(tmp_path))
    setup = repository.bootstrap(
        "user-a",
        _profile("2026-07-01"),
        GoalVersionInput(goal="maintenance", effective_from="2026-07-01"),
    )
    target = _target(setup.profile.id, setup.goal.id)

    first = repository.confirm_target(
        "user-a", "key-1", "fingerprint-a", target
    )
    repository.append_profile(
        "user-a", _profile("2026-07-03", weight_kg=68)
    )
    replay = repository.confirm_target(
        "user-a", "key-1", "fingerprint-a", target
    )

    assert first.replayed is False
    assert first.projection_completed is False
    assert replay.target == first.target
    assert replay.replayed is True
    assert replay.projection_completed is False
    assert repository.get_profile_version("user-a", setup.profile.id) == setup.profile
    assert repository.get_goal_version("user-a", setup.goal.id) == setup.goal

    completed = repository.mark_projection_complete(
        "user-a", "key-1", "fingerprint-a"
    )
    final_replay = repository.confirm_target(
        "user-a", "key-1", "fingerprint-a", target
    )

    assert completed.projection_completed is True
    assert final_replay.replayed is True
    assert final_replay.projection_completed is True


def test_get_confirmation_returns_saved_state_and_validates_fingerprint(tmp_path):
    repository = SQLiteProfileTargetRepository(_database(tmp_path))
    setup = repository.bootstrap(
        "user-a",
        _profile("2026-07-01"),
        GoalVersionInput(goal="maintenance", effective_from="2026-07-01"),
    )
    assert repository.get_confirmation("user-a", "missing", "fingerprint") is None
    created = repository.confirm_target(
        "user-a",
        "lookup-key",
        "lookup-fingerprint",
        _target(setup.profile.id, setup.goal.id),
    )

    pending = repository.get_confirmation(
        "user-a", "lookup-key", "lookup-fingerprint"
    )
    assert pending.target == created.target
    assert pending.replayed is True
    assert pending.projection_completed is False

    with pytest.raises(ProfileTargetRepositoryError) as raised:
        repository.get_confirmation(
            "user-a", "lookup-key", "changed-fingerprint"
        )
    assert raised.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_confirm_target_rejects_new_stale_preview_inside_transaction(tmp_path):
    repository = SQLiteProfileTargetRepository(_database(tmp_path))
    setup = repository.bootstrap(
        "user-a",
        _profile("2026-07-01"),
        GoalVersionInput(goal="maintenance", effective_from="2026-07-01"),
    )
    stale_target = _target(setup.profile.id, setup.goal.id)
    repository.append_goal(
        "user-a",
        GoalVersionInput(goal="fat_loss", effective_from="2026-07-03"),
    )

    with pytest.raises(ProfileTargetRepositoryError) as raised:
        repository.confirm_target(
            "user-a", "new-key", "fingerprint", stale_target
        )

    assert raised.value.code == "TARGET_PREVIEW_STALE"
    assert repository.list_targets("user-a") == ()


def test_delete_user_data_removes_owned_rows_and_preserves_other_users(tmp_path):
    repository = SQLiteProfileTargetRepository(_database(tmp_path))
    setup_a = repository.bootstrap(
        "user-a",
        _profile("2026-07-01"),
        GoalVersionInput(goal="fat_loss", effective_from="2026-07-01"),
    )
    setup_b = repository.bootstrap(
        "user-b",
        _profile("2026-07-01", weight_kg=80),
        GoalVersionInput(goal="muscle_gain", effective_from="2026-07-01"),
    )
    repository.confirm_target_once(
        "user-a", "delete-key-a", "fingerprint-a", _target(setup_a.profile.id, setup_a.goal.id)
    )
    target_b = repository.confirm_target_once(
        "user-b", "keep-key-b", "fingerprint-b", _target(setup_b.profile.id, setup_b.goal.id)
    )

    repository.delete_user_data("user-a")

    assert repository.get_setup("user-a").profile is None
    assert repository.get_setup("user-a").goal is None
    assert repository.get_setup("user-a").target is None
    assert repository.get_setup("user-b").profile == setup_b.profile
    assert repository.get_setup("user-b").goal == setup_b.goal
    assert repository.get_setup("user-b").target == target_b


def test_delete_user_data_rolls_back_all_rows_when_cleanup_fails(tmp_path):
    database = _database(tmp_path)
    repository = SQLiteProfileTargetRepository(database)
    setup = repository.bootstrap(
        "user-a",
        _profile("2026-07-01"),
        GoalVersionInput(goal="maintenance", effective_from="2026-07-01"),
    )
    target = repository.confirm_target_once(
        "user-a", "rollback-key", "rollback-fingerprint", _target(setup.profile.id, setup.goal.id)
    )
    with database.transaction() as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_target_cleanup
            BEFORE DELETE ON daily_target_versions
            BEGIN
                SELECT RAISE(ABORT, 'simulated cleanup failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError):
        repository.delete_user_data("user-a")

    assert repository.get_setup("user-a").profile == setup.profile
    assert repository.get_setup("user-a").goal == setup.goal
    assert repository.get_setup("user-a").target == target
    assert repository.confirm_target_once(
        "user-a", "rollback-key", "rollback-fingerprint", _target(setup.profile.id, setup.goal.id)
    ) == target


def _seed_complete_user_graph(database, user_id: str, prefix: str, target_id: str) -> None:
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO daily_logs (id, user_id, log_date, target_version_id)
            VALUES (?, ?, '2026-07-22', ?)
            """,
            (f"{prefix}-log", user_id, target_id),
        )
        connection.execute(
            """
            INSERT INTO food_catalog (
                id, owner_user_id, source, source_name, source_record_id, name,
                basis_type, basis_amount, unit, calories, carbs, protein, fat
            ) VALUES (?, ?, 'user_custom', 'test-foods', ?, 'Rice',
                      'per_100g', 100, 'g', 116, 25.9, 2.6, 0.3)
            """,
            (f"{prefix}-food", user_id, prefix),
        )
        for exercise_type in ("strength", "cardio"):
            connection.execute(
                """
                INSERT INTO exercise_catalog (
                    id, owner_user_id, source, source_name, source_record_id,
                    name, exercise_type, primary_muscle
                ) VALUES (?, ?, 'user_custom', 'test-exercises', ?, ?, ?, 'legs')
                """,
                (
                    f"{prefix}-{exercise_type}",
                    user_id,
                    f"{prefix}-{exercise_type}",
                    exercise_type.title(),
                    exercise_type,
                ),
            )
        connection.executemany(
            """
            INSERT INTO catalog_aliases (
                id, food_id, exercise_id, alias, normalized_alias, alias_kind
            ) VALUES (?, ?, ?, ?, ?, 'alias')
            """,
            (
                (f"{prefix}-food-alias", f"{prefix}-food", None, "rice", "rice"),
                (
                    f"{prefix}-strength-alias",
                    None,
                    f"{prefix}-strength",
                    "squat",
                    "squat",
                ),
                (
                    f"{prefix}-cardio-alias",
                    None,
                    f"{prefix}-cardio",
                    "run",
                    "run",
                ),
            ),
        )
        connection.executemany(
            """
            INSERT INTO catalog_search (
                catalog_kind, catalog_id, name, aliases, pinyin, source_tokens
            ) VALUES (?, ?, ?, ?, '', 'user custom')
            """,
            (
                ("food", f"{prefix}-food", "Rice", "rice"),
                ("exercise", f"{prefix}-strength", "Squat", "squat"),
                ("exercise", f"{prefix}-cardio", "Run", "run"),
            ),
        )
        connection.execute(
            """
            INSERT INTO catalog_favorites (id, user_id, food_id)
            VALUES (?, ?, ?)
            """,
            (f"{prefix}-favorite", user_id, f"{prefix}-food"),
        )
        connection.execute(
            """
            INSERT INTO catalog_usage (id, user_id, exercise_id)
            VALUES (?, ?, ?)
            """,
            (f"{prefix}-usage", user_id, f"{prefix}-strength"),
        )
        connection.execute(
            """
            INSERT INTO record_drafts (
                id, user_id, kind, schema_version, payload_json, expires_at
            ) VALUES (?, ?, 'meal', 1, '{}', '2026-08-22T00:00:00Z')
            """,
            (f"{prefix}-draft", user_id),
        )
        connection.execute(
            """
            INSERT INTO meals (
                id, user_id, log_date, name, meal_type, position, entry_method
            ) VALUES (?, ?, '2026-07-22', 'Lunch', 'lunch', 1, 'form')
            """,
            (f"{prefix}-meal", user_id),
        )
        connection.execute(
            """
            INSERT INTO meal_items (
                id, meal_id, catalog_food_id, food_name, amount, unit,
                basis_type, calories, carbs, protein, fat, source
            ) VALUES (?, ?, ?, 'Rice', 100, 'g', 'per_100g',
                      116, 25.9, 2.6, 0.3, 'user_custom')
            """,
            (f"{prefix}-meal-item", f"{prefix}-meal", f"{prefix}-food"),
        )
        connection.execute(
            """
            INSERT INTO training_sessions (
                id, user_id, log_date, title, entry_method
            ) VALUES (?, ?, '2026-07-22', 'Training', 'form')
            """,
            (f"{prefix}-session", user_id),
        )
        connection.execute(
            """
            INSERT INTO strength_exercises (
                id, session_id, catalog_exercise_id, exercise_name,
                primary_muscle, position
            ) VALUES (?, ?, ?, 'Squat', 'legs', 1)
            """,
            (
                f"{prefix}-strength-item",
                f"{prefix}-session",
                f"{prefix}-strength",
            ),
        )
        connection.execute(
            """
            INSERT INTO strength_sets (
                id, strength_exercise_id, set_number, reps, load_kg
            ) VALUES (?, ?, 1, 8, 80)
            """,
            (f"{prefix}-set", f"{prefix}-strength-item"),
        )
        connection.execute(
            """
            INSERT INTO cardio_items (
                id, session_id, catalog_exercise_id, activity_name,
                duration_min, position
            ) VALUES (?, ?, ?, 'Run', 20, 1)
            """,
            (f"{prefix}-cardio-item", f"{prefix}-session", f"{prefix}-cardio"),
        )


def _owned_graph_counts(database, user_id: str, prefix: str) -> dict[str, int]:
    user_tables = (
        "user_profile_versions",
        "overall_goal_versions",
        "daily_target_versions",
        "daily_logs",
        "catalog_favorites",
        "catalog_usage",
        "record_drafts",
        "meals",
        "training_sessions",
        "idempotency_keys",
    )
    id_tables = (
        "catalog_aliases",
        "meal_items",
        "strength_exercises",
        "strength_sets",
        "cardio_items",
    )
    with database.connection() as connection:
        counts = {
            table: connection.execute(
                f"SELECT COUNT(*) AS count FROM {table} WHERE user_id = ?",
                (user_id,),
            ).fetchone()["count"]
            for table in user_tables
        }
        counts.update(
            {
                table: connection.execute(
                    f"SELECT COUNT(*) AS count FROM {table} WHERE id LIKE ?",
                    (f"{prefix}-%",),
                ).fetchone()["count"]
                for table in id_tables
            }
        )
        counts["food_catalog"] = connection.execute(
            "SELECT COUNT(*) AS count FROM food_catalog WHERE owner_user_id = ?",
            (user_id,),
        ).fetchone()["count"]
        counts["exercise_catalog"] = connection.execute(
            "SELECT COUNT(*) AS count FROM exercise_catalog WHERE owner_user_id = ?",
            (user_id,),
        ).fetchone()["count"]
        counts["catalog_search"] = connection.execute(
            "SELECT COUNT(*) AS count FROM catalog_search WHERE catalog_id LIKE ?",
            (f"{prefix}-%",),
        ).fetchone()["count"]
    return counts


def test_delete_user_data_erases_complete_owned_graph_and_preserves_other_user(tmp_path):
    database = _database(tmp_path)
    repository = SQLiteProfileTargetRepository(database)
    setup_a = repository.bootstrap(
        "user-a",
        _profile("2026-07-01"),
        GoalVersionInput(goal="maintenance", effective_from="2026-07-01"),
    )
    setup_b = repository.bootstrap(
        "user-b",
        _profile("2026-07-01", weight_kg=80),
        GoalVersionInput(goal="muscle_gain", effective_from="2026-07-01"),
    )
    target_a = repository.confirm_target_once(
        "user-a", "complete-a", "fingerprint-a", _target(setup_a.profile.id, setup_a.goal.id)
    )
    target_b = repository.confirm_target_once(
        "user-b", "complete-b", "fingerprint-b", _target(setup_b.profile.id, setup_b.goal.id)
    )
    _seed_complete_user_graph(database, "user-a", "a", target_a.id)
    _seed_complete_user_graph(database, "user-b", "b", target_b.id)
    before_b = _owned_graph_counts(database, "user-b", "b")

    repository.delete_user_data("user-a")

    assert set(_owned_graph_counts(database, "user-a", "a").values()) == {0}
    assert _owned_graph_counts(database, "user-b", "b") == before_b


def test_catalog_search_deletion_uses_kind_when_food_and_exercise_ids_collide(tmp_path):
    database = _database(tmp_path)
    repository = SQLiteProfileTargetRepository(database)
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO food_catalog (
                id, owner_user_id, source, source_name, source_record_id, name,
                basis_type, basis_amount, unit, calories, carbs, protein, fat
            ) VALUES (
                'shared-id', 'user-a', 'user_custom', 'foods', 'a', 'Rice',
                'per_100g', 100, 'g', 116, 25.9, 2.6, 0.3
            )
            """
        )
        connection.execute(
            """
            INSERT INTO exercise_catalog (
                id, owner_user_id, source, source_name, source_record_id, name,
                exercise_type, primary_muscle
            ) VALUES (
                'shared-id', 'user-b', 'user_custom', 'exercises', 'b',
                'Squat', 'strength', 'legs'
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO catalog_search (
                catalog_kind, catalog_id, name, aliases, pinyin, source_tokens
            ) VALUES (?, 'shared-id', ?, '', '', 'user custom')
            """,
            (("food", "Rice"), ("exercise", "Squat")),
        )

    repository.delete_user_data("user-a")

    with database.connection() as connection:
        search_rows = connection.execute(
            """
            SELECT catalog_kind FROM catalog_search
            WHERE catalog_id = 'shared-id'
            """
        ).fetchall()
        food_count = connection.execute(
            "SELECT COUNT(*) AS count FROM food_catalog WHERE id = 'shared-id'"
        ).fetchone()["count"]
        exercise_count = connection.execute(
            "SELECT COUNT(*) AS count FROM exercise_catalog WHERE id = 'shared-id'"
        ).fetchone()["count"]

    assert [row["catalog_kind"] for row in search_rows] == ["exercise"]
    assert food_count == 0
    assert exercise_count == 1
