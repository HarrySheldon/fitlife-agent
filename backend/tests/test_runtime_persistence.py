import asyncio
from dataclasses import replace

import pytest

from backend.agent.contracts import AgentRunSnapshot
from backend.agent.persistence import VersionConflict
from backend.infrastructure.agent_runtime.memory_run_repository import MemoryRunRepository
from backend.agent.contracts import AgentCommand, AgentResult
from backend.agent.runtime import AgentRuntime


def test_execution_records_live_steps_and_terminal_state(repository):
    runtime = AgentRuntime(repository=repository)

    class Workflow:
        async def execute(self, command, context):
            async def operation():
                run = await runtime.get_status(runtime.active_run_ids[0], "user")
                assert run.current_step == "planner"
                assert run.attempt == 1
                assert run.status == "running"
                return "done"
            await context.step("planner", operation)
            return AgentResult("answer", "chat", {}, {}, (), "mock")

    outcome = asyncio.run(runtime.execute(AgentCommand("chat", "private question", "user"), Workflow()))
    run = repository.get(outcome.run_id, "user")
    assert run.status == "succeeded"
    assert run.created_at and run.started_at and run.finished_at and run.deadline_at
    assert run.input_chars > 0 and run.input_tokens > 0
    assert "private question" not in repr(run)
    assert [event.event_type for event in repository.events(run.run_id, "user")] == [
        "RUN_ACCEPTED", "RUN_STARTED", "STEP_STARTED", "STEP_SUCCEEDED", "RUN_SUCCEEDED"]


@pytest.fixture(params=["memory", "sqlite"])
def repository(request, tmp_path):
    if request.param == "memory":
        return MemoryRunRepository()
    from backend.infrastructure.agent_runtime.sqlite_run_repository import SQLiteRunRepository
    return SQLiteRunRepository(tmp_path / "agent_runtime.sqlite3")


def test_run_transition_and_event_are_versioned_and_atomic(repository):
    run = repository.create(AgentRunSnapshot("run", "request", "user", "chat", "accepted"))
    running = repository.update(replace(run, status="running"), "RUN_STARTED")
    with pytest.raises(VersionConflict):
        repository.update(replace(run, status="failed"), "RUN_FAILED")
    assert repository.get("run", "user") == running
    assert [event.event_type for event in repository.events("run", "user")] == ["RUN_ACCEPTED", "RUN_STARTED"]
    assert [event.seq for event in repository.events("run", "user")] == [1, 2]
    with pytest.raises(KeyError):
        repository.get("run", "other-user")


def test_invalid_payload_and_terminal_updates_never_append(repository):
    from backend.agent.persistence import InvalidTransition
    run = repository.create(AgentRunSnapshot("run", "request", "user", "chat", "accepted"))
    for payload in ({"prompt": "secret"}, {"duration_ms": float("nan")}, {"delay_ms": float("inf")}, {"error_type": "PrivateHealthException"}):
        with pytest.raises(ValueError):
            repository.update(replace(run, status="running"), "RUN_STARTED", payload)
    assert len(repository.events("run", "user")) == 1
    terminal = repository.update(replace(run, status="failed"), "RUN_FAILED")
    with pytest.raises(InvalidTransition):
        repository.update(terminal, "STEP_SUCCEEDED")
    assert len(repository.events("run", "user")) == 2


def test_failure_is_durable_and_redacted(repository):
    class PrivateError(Exception):
        code = "secret_health_details"
        retryable = False

    class Workflow:
        async def execute(self, command, context):
            await context.step("planner", lambda: (_ for _ in ()).throw(PrivateError("private response and api key")))

    runtime = AgentRuntime(repository=repository)
    with pytest.raises(PrivateError) as raised:
        asyncio.run(runtime.execute(AgentCommand("chat", "secret prompt", "user"), Workflow()))
    run = repository.get(raised.value.run_id, "user")
    assert run.status == "failed" and run.public_error_code == "INTERNAL_ERROR"
    assert len(run.internal_error_id) == 32
    assert run.failure_stage == "planner"
    assert repository.events(run.run_id, "user")[-1].payload["internal_error_id"] == run.internal_error_id
    assert "private" not in repr(run) + repr(repository.events(run.run_id, "user"))


def test_checkpoint_metadata_is_separate_and_survives_reopen(tmp_path):
    from backend.infrastructure.agent_runtime.sqlite_run_repository import SQLiteRunRepository
    from backend.infrastructure.agent_runtime.sqlite_checkpoint_store import SQLiteCheckpointStore
    from backend.agent.persistence import InvalidTransition
    path = tmp_path / "agent_runtime.sqlite3"
    repository = SQLiteRunRepository(path)
    run = repository.create(AgentRunSnapshot("r", "q", "u", "chat", "accepted"))
    store = SQLiteCheckpointStore(repository)
    store.save("r", "u", "planner", {"completed": True, "attempt": 2})
    reopened = SQLiteRunRepository(path)
    assert SQLiteCheckpointStore(reopened).get("r", "u", "planner").state == {"completed": True, "attempt": 2}
    assert reopened.get("r", "u") == run
    assert len(reopened.events("r", "u")) == 1
    with pytest.raises(ValueError):
        store.save("r", "u", "planner", {"prompt": "private"})
    with pytest.raises(KeyError):
        store.get("r", "intruder", "planner")
    repository.update(replace(run, status="failed"), "RUN_FAILED")
    with pytest.raises(InvalidTransition):
        store.save("r", "u", "planner", {"completed": True})


def test_repository_unavailable_cannot_return_success():
    class Unavailable(MemoryRunRepository):
        def create(self, run):
            raise OSError("database unavailable")
    class Workflow:
        async def execute(self, command, context):
            pytest.fail("must not execute without authoritative state")
    with pytest.raises(OSError):
        asyncio.run(AgentRuntime(repository=Unavailable()).execute(AgentCommand("chat", "q", None), Workflow()))


@pytest.mark.parametrize("fail_event", ["create", "RUN_STARTED", "RUN_SUCCEEDED", "RUN_FAILED"])
def test_repository_errors_always_keep_correlation_ids(fail_event):
    class Unavailable(MemoryRunRepository):
        def create(self, run):
            if fail_event == "create":
                raise OSError("private database path")
            return super().create(run)
        def update(self, run, event_type, payload=None):
            if event_type == fail_event:
                raise OSError("private database path")
            return super().update(run, event_type, payload)
    class Workflow:
        async def execute(self, command, context):
            if fail_event == "RUN_FAILED":
                raise ValueError("business failure")
            return AgentResult("ok", "chat", {}, {}, (), "mock")
    with pytest.raises(OSError) as raised:
        asyncio.run(AgentRuntime(repository=Unavailable()).execute(AgentCommand("chat", "q", None), Workflow()))
    assert raised.value.run_id and raised.value.request_id


def test_real_factory_uses_current_settings_and_sqlite(tmp_path, monkeypatch, isolated_agent_runtime):
    from backend.config import Settings
    from backend.infrastructure.agent_runtime import factory
    from backend.infrastructure.agent_runtime.sqlite_run_repository import SQLiteRunRepository
    monkeypatch.setattr(factory, "get_settings", lambda: Settings(data_dir=tmp_path))
    production_factory = isolated_agent_runtime
    runtime = production_factory()
    assert production_factory() is runtime
    class Workflow:
        async def execute(self, command, context):
            context.set_model_metadata(provider="mock", model="test-model")
            await context.step("planner", lambda: "done")
            context.checkpoint("planner", {"completed": True, "attempt": 1})
            context.consume_output("ok")
            return AgentResult("ok", "chat", {}, {}, (), "test-model")
    result = runtime.execute_sync(AgentCommand("chat", "q", "u"), Workflow())
    reopened = SQLiteRunRepository(tmp_path / "agent_runtime.sqlite3")
    run = reopened.get(result.run_id, "u")
    assert (run.provider, run.model, run.output_tokens) == ("mock", "test-model", 1)
    assert len(reopened.events(result.run_id, "u")) == 5
    assert not (tmp_path / "fitlife.sqlite3").exists()
    monkeypatch.setattr(factory, "get_settings", lambda: Settings(data_dir=tmp_path / "next"))
    assert production_factory() is not runtime


def test_runtime_telemetry_has_tool_model_and_retry_parentage(repository):
    from backend.agent.telemetry import InMemoryTelemetryContext
    from backend.agent.policy import RuntimePolicy, RetryPolicy
    telemetry = InMemoryTelemetryContext()
    attempts = 0
    class Workflow:
        async def execute(self, command, context):
            async def model():
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise ConnectionError("secret provider response")
                return "ok"
            await context.step("planner", lambda: context.tool("plan_route_model", "safe", model))
            return AgentResult("ok", "chat", {}, {}, (), "mock")
    runtime = AgentRuntime(repository=repository, telemetry=telemetry,
                           policy=RuntimePolicy(retry=RetryPolicy(base_delay_seconds=0)))
    outcome = runtime.execute_sync(AgentCommand("chat", "private question", "u"), Workflow())
    spans = telemetry.spans
    run = spans[0]
    step = next(span for span in spans if span.name == "fitlife.agent.step")
    tool = next(span for span in spans if span.name == "fitlife.agent.tool")
    assert step.parent_id == run.span_id and tool.parent_id == step.span_id
    assert all(span.parent_id == tool.span_id for span in spans if span.name in {"fitlife.ai.request", "fitlife.agent.retry_wait"})
    assert len([span for span in spans if span.name == "fitlife.ai.request"]) == 2
    assert "private" not in repr(spans) and "secret" not in repr(spans)
    events = repository.events(outcome.run_id, "u")
    assert sum(event.event_type == "STEP_RETRY_SCHEDULED" for event in events) == 1
    assert repository.get(outcome.run_id, "u").tool_calls == 2
    assert run.attributes["tool_calls"] == 2
    assert run.attributes["model_calls"] == 2
    assert run.attributes["retry_count"] == 1


def test_late_worker_cannot_change_terminal_snapshot(repository):
    from threading import Event
    from backend.agent.policy import RuntimePolicy
    from backend.agent.runtime import RunTimedOut
    release, done = Event(), Event()
    class Workflow:
        async def execute(self, command, context):
            def blocked():
                release.wait(2)
                try:
                    context.checkpoint("planner", {"completed": True})
                except RunTimedOut:
                    pass
                except Exception:
                    pass
                finally:
                    done.set()
                return "late"
            await context.step("planner", blocked)
    runtime = AgentRuntime(repository=repository, policy=RuntimePolicy(deadline_seconds=0.03))
    with pytest.raises(RunTimedOut) as raised:
        runtime.execute_sync(AgentCommand("chat", "q", "u"), Workflow())
    before = repository.get(raised.value.run_id, "u")
    events = repository.events(before.run_id, "u")
    release.set()
    assert done.wait(2)
    assert repository.get(before.run_id, "u") == before
    assert repository.events(before.run_id, "u") == events
