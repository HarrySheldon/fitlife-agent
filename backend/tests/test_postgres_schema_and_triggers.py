"""Phase 3 tests for PostgreSQL schema migrations, triggers, FTS, and savepoints."""
from __future__ import annotations

import pytest

from backend.infrastructure.postgres.errors import DatabaseIntegrityError
from backend.infrastructure.postgres.migrations import run_migrations
from backend.infrastructure.postgres.schema import Migration, RECORDS_MIGRATIONS


def test_postgres_migrations_apply_and_are_idempotent(make_isolated_pg_db):
    db = make_isolated_pg_db(initialize=False)
    run_migrations(db, RECORDS_MIGRATIONS)
    run_migrations(db, RECORDS_MIGRATIONS)
    with db.connection() as conn:
        row = conn.execute("SELECT MAX(version) AS max_ver FROM schema_migrations").fetchone()
    assert int(row["max_ver"]) == RECORDS_MIGRATIONS[-1].version


def test_modified_migration_checksum_is_rejected(make_isolated_pg_db):
    db = make_isolated_pg_db()
    altered = (
        Migration(version=1, name="core_users_and_preferences", statements=("SELECT 1",)),
        *RECORDS_MIGRATIONS[1:],
    )
    with pytest.raises(RuntimeError, match="checksum"):
        run_migrations(db, altered)


def test_json_validation_and_integrity_triggers_enforce_constraints(pg_db):
    with pg_db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO users (
                user_id, username, display_name, password_hash,
                token_version, created_at
            ) VALUES ('u1', 'alice', 'Alice', 'hash', 1, '2026-01-01T00:00:00Z')
            """
        )

    # Invalid JSON array in profile_safety_versions must be rejected by trigger
    with pytest.raises(DatabaseIntegrityError):
        with pg_db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO profile_safety_versions (
                    id, user_id, allergies_or_restrictions_json, created_at
                ) VALUES ('s1', 'u1', '{"not":"array"}', '2026-01-01T00:00:00Z')
                """
            )


def test_catalog_search_generated_tsvector_matches_queries(pg_db):
    with pg_db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO food_catalog (
                id, source, source_name, source_record_id, dataset_version, name,
                basis_type, basis_amount, unit, calories, carbs, protein, fat,
                active, created_at, updated_at
            ) VALUES (
                'food-chicken-1', 'public', 'test', 'rec-1', 'v1', 'Chicken Breast',
                'per_100g', 100.0, 'g', 165.0, 0.0, 31.0, 3.6,
                1, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO catalog_search (
                catalog_kind, catalog_id, name, aliases, pinyin, source_tokens
            ) VALUES (
                'food', 'food-chicken-1', 'Chicken Breast', 'grilled poultry', '', 'chicken breast poultry'
            )
            """
        )
        hits = conn.execute(
            """
            SELECT catalog_id
            FROM catalog_search
            WHERE search_tsv @@ to_tsquery('simple', 'chicken:* & breast:*')
            """
        ).fetchall()
    assert [row["catalog_id"] for row in hits] == ["food-chicken-1"]


def test_savepoint_recovers_from_integrity_error_inside_transaction(pg_db):
    with pg_db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO users (
                user_id, username, display_name, password_hash,
                token_version, created_at
            ) VALUES ('u1', 'alice', 'Alice', 'h', 1, '2026-01-01T00:00:00Z')
            """
        )
        caught = False
        try:
            with conn.savepoint():
                conn.execute(
                    """
                    INSERT INTO users (
                        user_id, username, display_name, password_hash,
                        token_version, created_at
                    ) VALUES ('u1', 'alice', 'Dup', 'h', 1, '2026-01-01T00:00:00Z')
                    """
                )
        except DatabaseIntegrityError:
            caught = True
        assert caught is True
        # Outer transaction must still be healthy and committable!
        conn.execute(
            "INSERT INTO user_preferences (user_id, language, unit_system, timezone, updated_at) VALUES ('u1', 'zh-CN', 'metric', 'UTC', '2026-01-01T00:00:00Z')"
        )

    with pg_db.connection() as conn:
        row = conn.execute("SELECT language FROM user_preferences WHERE user_id = 'u1'").fetchone()
    assert row is not None and row["language"] == "zh-CN"
