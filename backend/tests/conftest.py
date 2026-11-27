from __future__ import annotations

import os
import time
from uuid import uuid4

import pytest

from backend.config import get_settings
from backend.infrastructure.postgres.database import PostgresDatabase, reset_database_pools
from backend.infrastructure.postgres.errors import DatabaseOperationalError
from backend.infrastructure.postgres.runtime import ensure_database_ready
from backend.rag.retriever import clear_index_cache
from backend import evaluation

TEST_DATABASE_URL = os.environ.get(
    "FITLIFE_TEST_DATABASE_URL",
    "postgresql://fitlife:fitlife@127.0.0.1:15432/fitlife_test",
)


@pytest.fixture(scope="session", autouse=True)
def _ensure_test_database():
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ.pop("DATABASE_SCHEMA", None)
    get_settings.cache_clear()
    db = PostgresDatabase(TEST_DATABASE_URL)
    ensure_database_ready(db)
    yield
    reset_database_pools()


def _truncate_public_tables(database: PostgresDatabase) -> None:
    sql = """
        DO $truncate$
        DECLARE
            tbl TEXT;
            has_rows BOOLEAN;
            dirty TEXT[] := ARRAY[]::TEXT[];
        BEGIN
            FOR tbl IN
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public' AND tablename != 'schema_migrations'
                ORDER BY tablename
            LOOP
                EXECUTE format('SELECT EXISTS (SELECT 1 FROM public.%I LIMIT 1)', tbl) INTO has_rows;
                IF has_rows THEN
                    dirty := array_append(dirty, format('public.%I', tbl));
                END IF;
            END LOOP;
            IF COALESCE(array_length(dirty, 1), 0) > 0 THEN
                EXECUTE 'TRUNCATE TABLE ' || array_to_string(dirty, ', ') || ' RESTART IDENTITY CASCADE';
            END IF;
        END
        $truncate$
        """
    for attempt in range(4):
        try:
            with database.connection() as connection:
                connection.execute(sql)
            return
        except DatabaseOperationalError as error:
            if (error.sqlstate == "40P01" or "deadlock detected" in str(error).casefold()) and attempt < 3:
                time.sleep(0.05 * (attempt + 1))
                continue
            raise


@pytest.fixture(autouse=True)
def _isolate_test_state(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.delenv("DATABASE_SCHEMA", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr(evaluation, "data_path", lambda name: tmp_path / name)

    _truncate_public_tables(PostgresDatabase(TEST_DATABASE_URL))
    clear_index_cache()

    from backend.api import coach_conversations, plan_adjustment
    from backend.infrastructure.agent_runtime import factory as runtime_factory

    coach_conversations._SERVICES.clear()
    plan_adjustment.reset_plan_adjustment_services()
    runtime_factory._runtime = None
    runtime_factory._target_key = None

    yield

    clear_index_cache()
    coach_conversations._SERVICES.clear()
    plan_adjustment.reset_plan_adjustment_services()
    runtime_factory._runtime = None
    runtime_factory._target_key = None
    get_settings.cache_clear()


@pytest.fixture()
def pg_db() -> PostgresDatabase:
    return PostgresDatabase(TEST_DATABASE_URL)


@pytest.fixture()
def make_isolated_pg_db():
    created: list[PostgresDatabase] = []

    def _make(*, initialize: bool = True) -> PostgresDatabase:
        db = PostgresDatabase(TEST_DATABASE_URL, schema=f"test_{uuid4().hex[:12]}")
        db.create_schema()
        if initialize:
            ensure_database_ready(db)
        created.append(db)
        return db

    yield _make

    for db in reversed(created):
        try:
            db.drop_schema()
        except Exception:
            pass


@pytest.fixture()
def isolated_agent_runtime():
    from backend.infrastructure.agent_runtime import factory as runtime_factory

    runtime_factory._runtime = None
    runtime_factory._target_key = None
    try:
        yield runtime_factory.get_agent_runtime
    finally:
        runtime_factory._runtime = None
        runtime_factory._target_key = None
