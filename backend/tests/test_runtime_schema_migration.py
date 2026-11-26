"""A persisted PostgreSQL runtime schema must retain canonical columns and transactional initialization."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from backend.agent.contracts import AgentCommand, AgentResult, AgentRunSnapshot
from backend.agent.runtime import AgentRuntime
from backend.infrastructure.agent_runtime.postgres_checkpoint_store import PostgresCheckpointStore
from backend.infrastructure.agent_runtime.postgres_run_repository import PostgresRunRepository
from backend.infrastructure.postgres.errors import DatabaseOperationalError
from backend.infrastructure.postgres.runtime import ensure_database_ready


class _RecordingWorkflow:
    async def execute(self, command, context):
        return AgentResult("answer", "chat", {}, {}, (), "mock")


def test_runtime_schema_has_canonical_columns_and_preserves_history(make_isolated_pg_db):
    database = make_isolated_pg_db()
    repository = PostgresRunRepository(database)
    repository.create(AgentRunSnapshot("legacy-run", "legacy-request", "user", "chat", "accepted"))

    with database.connection() as connection:
        columns = {
            row[0]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'agent_runs'"
            ).fetchall()
        }
    assert "id" in columns
    assert "task_id" in columns
    assert "task_version" in columns
    assert "run_id" not in columns
    assert repository.get("legacy-run", "user").status == "accepted"
    assert repository.get("legacy-run", "user").task_id is None
    assert repository.get("legacy-run", "user").task_version is None


def test_checkpoints_and_linked_runs_persist_across_reopen(make_isolated_pg_db):
    database = make_isolated_pg_db()
    repository = PostgresRunRepository(database)
    unlinked = AgentRunSnapshot("legacy-run", "legacy-request", "user", "chat", "accepted")
    repository.create(unlinked)
    PostgresCheckpointStore(repository).save("legacy-run", "user", "planner", {"completed": True, "attempt": 1})

    linked = AgentRunSnapshot("linked", "linked-request", "user", "chat", "accepted",
                              task_id="task", task_version=2)
    repository.create(linked)
    reopened = PostgresRunRepository(database)
    assert reopened.get("linked", "user") == linked
    assert reopened.get("legacy-run", "user").task_id is None
    assert PostgresCheckpointStore(reopened).get("legacy-run", "user", "planner").state == {"completed": True, "attempt": 1}


def test_migrated_database_accepts_new_runs(make_isolated_pg_db):
    database = make_isolated_pg_db()

    runtime = AgentRuntime(repository=PostgresRunRepository(database))
    outcome = runtime.execute_sync(AgentCommand("chat", "question", "user"), _RecordingWorkflow())

    assert outcome.status == "succeeded"
    assert asyncio.run(runtime.get_status(outcome.run_id, "user")).status == "succeeded"


def test_current_layout_is_left_untouched(make_isolated_pg_db):
    database = make_isolated_pg_db()
    repository = PostgresRunRepository(database)
    with database.connection() as connection:
        first_columns = tuple(
            row[0]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'agent_runs' "
                "ORDER BY ordinal_position"
            ).fetchall()
        )

    ensure_database_ready(database)

    with database.connection() as connection:
        second_columns = tuple(
            row[0]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'agent_runs' "
                "ORDER BY ordinal_position"
            ).fetchall()
        )
    assert second_columns == first_columns
    assert repository.get is not None


def test_concurrent_runtime_initialization_is_atomic_and_repeatable(make_isolated_pg_db):
    for _trial in range(3):
        database = make_isolated_pg_db(initialize=False)
        barrier = Barrier(2)

        def initialize():
            barrier.wait(timeout=5)
            ensure_database_ready(database)
            return PostgresRunRepository(database)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(initialize) for _ in range(2)]
            repositories = [future.result(timeout=30) for future in futures]
        for repository in (*repositories, PostgresRunRepository(database)):
            with repository.database.connection() as connection:
                columns = [
                    row[0]
                    for row in connection.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = 'agent_runs'"
                    ).fetchall()
                ]
                assert columns.count("task_id") == columns.count("task_version") == 1
                assert "id" in columns and "run_id" not in columns
                latest_version = connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0]
                assert latest_version == 16


def test_finalization_failure_keeps_the_original_error_attached(make_isolated_pg_db, monkeypatch):
    """A storage failure while recording the outcome must not hide the cause.

    Only the terminal write may fail here. If the run could not even start, the
    original error would legitimately be the storage error, which is the
    different (and correct) behaviour covered by the migration tests.
    """
    database = make_isolated_pg_db()
    repository = PostgresRunRepository(database)
    runtime = AgentRuntime(repository=repository)

    real_update = repository.update
    calls = []

    def failing_terminal_write(run, event_type, payload=None):
        calls.append(event_type)
        if event_type == "RUN_FAILED":
            raise DatabaseOperationalError("disk I/O error")
        return real_update(run, event_type, payload)

    monkeypatch.setattr(repository, "update", failing_terminal_write)

    class FailingWorkflow:
        async def execute(self, command, context):
            raise ValueError("the real business failure")

    with pytest.raises(DatabaseOperationalError) as captured:
        runtime.execute_sync(AgentCommand("chat", "question", "user"), FailingWorkflow())

    assert calls[-1] == "RUN_FAILED"
    assert captured.value.run_id
    assert captured.value.request_id
    assert isinstance(captured.value.finalization_error, ValueError)
    assert "the real business failure" in str(captured.value.finalization_error)
