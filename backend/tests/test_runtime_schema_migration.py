"""A persisted runtime database must never be adopted with a stale key column.

Both the legacy and the current layout stamp ``PRAGMA user_version = 1``, so the
version check cannot detect the difference. A legacy database previously made
every run write fail with "no such column: id" from inside the finalisation
path, which also hid the original error from the caller.
"""
import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from backend.agent.contracts import AgentCommand, AgentResult
from backend.agent.runtime import AgentRuntime
from backend.infrastructure.agent_runtime.sqlite_run_repository import SQLiteRunRepository


LEGACY_RUNS_DDL = """
CREATE TABLE agent_runs (
    run_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
    user_id TEXT, operation TEXT NOT NULL, status TEXT NOT NULL,
    current_step TEXT, attempt INTEGER NOT NULL, public_error_code TEXT,
    created_at TEXT NOT NULL, started_at TEXT, deadline_at TEXT NOT NULL,
    finished_at TEXT, policy_version TEXT NOT NULL, policy_snapshot_json TEXT NOT NULL,
    provider TEXT, model TEXT, input_chars INTEGER NOT NULL,
    input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, tool_calls INTEGER NOT NULL,
    internal_error_id TEXT, failure_stage TEXT, version INTEGER NOT NULL
)
"""


def _legacy_database(path):
    connection = sqlite3.connect(path)
    with connection:
        connection.execute(LEGACY_RUNS_DDL)
        connection.execute(
            "INSERT INTO agent_runs VALUES ('legacy-run', 'legacy-request', 'user', 'chat', "
            "'succeeded', 'result_projector', 1, NULL, '2026-01-01T00:00:00+00:00', "
            "'2026-01-01T00:00:00+00:00', '2026-01-01T00:01:00+00:00', "
            "'2026-01-01T00:00:01+00:00', 'default-v1', '{}', 'openai', 'gpt', 10, 3, 4, 1, "
            "NULL, NULL, 1)"
        )
        connection.execute(
            "CREATE TABLE agent_run_events (run_id TEXT NOT NULL, seq INTEGER NOT NULL, "
            "event_type TEXT NOT NULL, step TEXT, attempt INTEGER, occurred_at TEXT NOT NULL, "
            "payload_json TEXT NOT NULL, PRIMARY KEY(run_id, seq))"
        )
        connection.execute("PRAGMA user_version=1")
    connection.close()


class _RecordingWorkflow:
    async def execute(self, command, context):
        return AgentResult("answer", "chat", {}, {}, (), "mock")


def test_legacy_run_key_is_migrated_and_history_is_preserved(tmp_path):
    path = tmp_path / "agent_runtime.sqlite3"
    _legacy_database(path)

    repository = SQLiteRunRepository(path)

    columns = {
        row[1]
        for row in sqlite3.connect(path).execute("PRAGMA table_info(agent_runs)")
    }
    assert "id" in columns
    assert "run_id" not in columns
    assert repository.get("legacy-run", "user").status == "succeeded"
    assert repository.get("legacy-run", "user").task_id is None
    assert repository.get("legacy-run", "user").task_version is None


@pytest.mark.parametrize("legacy_key", [True, False])
def test_old_layout_preserves_checkpoints_and_accepts_linked_run(tmp_path, legacy_key):
    from backend.agent.contracts import AgentRunSnapshot
    from backend.infrastructure.agent_runtime.sqlite_checkpoint_store import SQLiteCheckpointStore

    path = tmp_path / "old.sqlite3"
    _legacy_database(path)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE agent_checkpoints (run_id TEXT NOT NULL, name TEXT NOT NULL, state_json TEXT NOT NULL, version INTEGER NOT NULL, PRIMARY KEY(run_id, name))")
        connection.execute("INSERT INTO agent_checkpoints VALUES (?, ?, ?, ?)",
                           ("legacy-run", "planner", '{"completed": true, "attempt": 1}', 1))
        if not legacy_key:
            connection.execute("ALTER TABLE agent_runs RENAME COLUMN run_id TO id")
    repository = SQLiteRunRepository(path)
    linked = AgentRunSnapshot("linked", "linked-request", "user", "chat", "accepted",
                              task_id="task", task_version=2)
    repository.create(linked)
    reopened = SQLiteRunRepository(path)
    assert reopened.get("linked", "user") == linked
    assert reopened.get("legacy-run", "user").task_id is None
    assert SQLiteCheckpointStore(reopened).get("legacy-run", "user", "planner").state == {"completed": True, "attempt": 1}


def test_migrated_database_accepts_new_runs(tmp_path):
    path = tmp_path / "agent_runtime.sqlite3"
    _legacy_database(path)

    runtime = AgentRuntime(repository=SQLiteRunRepository(path))
    outcome = runtime.execute_sync(AgentCommand("chat", "question", "user"), _RecordingWorkflow())

    assert outcome.status == "succeeded"
    assert asyncio.run(runtime.get_status(outcome.run_id, "user")).status == "succeeded"


def test_current_layout_is_left_untouched(tmp_path):
    path = tmp_path / "agent_runtime.sqlite3"
    repository = SQLiteRunRepository(path)
    first_columns = tuple(
        row[1] for row in sqlite3.connect(path).execute("PRAGMA table_info(agent_runs)")
    )

    SQLiteRunRepository(path)

    assert tuple(
        row[1] for row in sqlite3.connect(path).execute("PRAGMA table_info(agent_runs)")
    ) == first_columns
    assert repository.get is not None


@pytest.mark.parametrize("layout", ["id", "run_id", "new"])
def test_concurrent_runtime_initialization_is_atomic_and_repeatable(tmp_path, layout):
    for trial in range(10):
        path = tmp_path / f"runtime-{trial}.sqlite3"
        if layout != "new":
            _legacy_database(path)
            if layout == "id":
                with sqlite3.connect(path) as connection:
                    connection.execute("ALTER TABLE agent_runs RENAME COLUMN run_id TO id")
        barrier = Barrier(2)

        def initialize():
            barrier.wait(timeout=5)
            return SQLiteRunRepository(path)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(initialize) for _ in range(2)]
            repositories = [future.result(timeout=15) for future in futures]
        for repository in (*repositories, SQLiteRunRepository(path)):
            if layout != "new":
                run = repository.get("legacy-run", "user")
                assert run.status == "succeeded" and run.task_id is None
            with repository.connect() as connection:
                columns = [row[1] for row in connection.execute("PRAGMA table_info(agent_runs)")]
                assert columns.count("task_id") == columns.count("task_version") == 1
                assert "id" in columns and "run_id" not in columns
                assert connection.execute("PRAGMA user_version").fetchone()[0] == 2


def test_finalization_failure_keeps_the_original_error_attached(tmp_path, monkeypatch):
    """A storage failure while recording the outcome must not hide the cause.

    Only the terminal write may fail here. If the run could not even start, the
    original error would legitimately be the storage error, which is the
    different (and correct) behaviour covered by the migration tests.
    """
    path = tmp_path / "agent_runtime.sqlite3"
    repository = SQLiteRunRepository(path)
    runtime = AgentRuntime(repository=repository)

    real_update = repository.update
    calls = []

    def failing_terminal_write(run, event_type, payload=None):
        calls.append(event_type)
        if event_type == "RUN_FAILED":
            raise sqlite3.OperationalError("disk I/O error")
        return real_update(run, event_type, payload)

    monkeypatch.setattr(repository, "update", failing_terminal_write)

    class FailingWorkflow:
        async def execute(self, command, context):
            raise ValueError("the real business failure")

    with pytest.raises(sqlite3.OperationalError) as captured:
        runtime.execute_sync(AgentCommand("chat", "question", "user"), FailingWorkflow())

    assert calls[-1] == "RUN_FAILED"
    assert captured.value.run_id
    assert captured.value.request_id
    assert isinstance(captured.value.finalization_error, ValueError)
    assert "the real business failure" in str(captured.value.finalization_error)
