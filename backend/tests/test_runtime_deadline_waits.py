import asyncio
import time
from threading import BoundedSemaphore, Event
from types import SimpleNamespace

import pytest

from backend.agent.contracts import AgentCommand
from backend.agent.policy import RetryPolicy, RuntimePolicy
from backend.agent.runtime import AgentRuntime, RunCancelled, RunTimedOut, RuntimeContext


def test_async_operation_is_interrupted_at_deadline():
    context = RuntimeContext(policy=RuntimePolicy(deadline_seconds=0.03))

    async def hanging():
        await asyncio.sleep(0.3)

    started = time.monotonic()
    with pytest.raises(RunTimedOut):
        asyncio.run(context.tool("hanging", "safe", hanging))
    assert time.monotonic() - started < 0.2
    assert context.completed_tools == []


def test_sync_entry_returns_before_blocking_operation_finishes():
    context_seen = []

    class Workflow:
        async def execute(self, command, context):
            context_seen.append(context)
            await context.tool("blocking", "safe", lambda: time.sleep(0.3))
            raise AssertionError("A late result must not start the next step")

    runtime = AgentRuntime(policy=RuntimePolicy(deadline_seconds=0.03))
    started = time.monotonic()
    with pytest.raises(RunTimedOut) as raised:
        runtime.execute_sync(AgentCommand("chat", "hello", "u"), Workflow())
    assert time.monotonic() - started < 0.2
    time.sleep(0.35)
    assert context_seen[0].completed_tools == []
    assert asyncio.run(runtime.get_status(raised.value.run_id, "u")).status == "timed_out"


def test_workflow_without_context_steps_is_bounded():
    class Workflow:
        async def execute(self, command, context):
            await asyncio.Event().wait()

    runtime = AgentRuntime(policy=RuntimePolicy(deadline_seconds=0.03))
    started = time.monotonic()
    with pytest.raises(RunTimedOut):
        runtime.execute_sync(AgentCommand("chat", "hello", "u"), Workflow())
    assert time.monotonic() - started < 0.2


def test_cancellation_interrupts_retry_backoff():
    async def scenario():
        entered_backoff = asyncio.Event()
        attempts = []

        async def sleeper(delay):
            entered_backoff.set()
            await asyncio.sleep(delay)

        def fail():
            attempts.append(1)
            raise ConnectionError("temporary")

        class Workflow:
            async def execute(self, command, context):
                await context.tool("provider", "safe", fail)

        runtime = AgentRuntime(
            policy=RuntimePolicy(retry=RetryPolicy(base_delay_seconds=5)), sleeper=sleeper,
        )
        task = asyncio.create_task(runtime.execute(AgentCommand("chat", "hello", "u"), Workflow()))
        await entered_backoff.wait()
        started = time.monotonic()
        await runtime.cancel(runtime.active_run_ids[0], "u")
        with pytest.raises(RunCancelled):
            await task
        assert time.monotonic() - started < 0.2
        assert attempts == [1]

    asyncio.run(scenario())


def test_deadline_interrupts_a_slow_backoff_sleeper():
    attempts = []

    async def fail():
        attempts.append(1)
        raise ConnectionError("temporary")

    async def slow_sleeper(delay):
        await asyncio.sleep(0.3)

    context = RuntimeContext(
        policy=RuntimePolicy(deadline_seconds=0.03, retry=RetryPolicy(base_delay_seconds=0.001)),
        sleeper=slow_sleeper,
    )
    started = time.monotonic()
    with pytest.raises(RunTimedOut):
        asyncio.run(context.tool("provider", "safe", fail))
    assert time.monotonic() - started < 0.2
    assert attempts == [1]


def test_sync_cancellation_discards_late_result():
    started_worker, release = Event(), Event()
    contexts = []

    def blocking():
        started_worker.set()
        release.wait(1)
        return "late"

    class Workflow:
        async def execute(self, command, context):
            contexts.append(context)
            await context.step("blocking", blocking)
            raise AssertionError("late result advanced workflow")

    async def scenario():
        runtime = AgentRuntime()
        task = asyncio.create_task(runtime.execute(AgentCommand("chat", "hello", "u"), Workflow()))
        while not started_worker.is_set():
            await asyncio.sleep(0.001)
        run_id = runtime.active_run_ids[0]
        started = time.monotonic()
        await runtime.cancel(run_id, "u")
        with pytest.raises(RunCancelled):
            await task
        assert time.monotonic() - started < 0.2
        release.set()
        await asyncio.sleep(0.02)
        assert contexts[0].completed_steps == ["input_guard"]
        assert (await runtime.get_status(run_id, "u")).status == "cancelled"

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_worker_capacity_wait_is_bounded_and_does_not_start_extra_work(monkeypatch):
    import backend.agent.runtime as runtime_module

    monkeypatch.setattr(runtime_module, "_SYNC_SLOTS", BoundedSemaphore(1))
    release = Event()
    entered = Event()
    extra_calls = []

    def blocking():
        entered.set()
        release.wait(1)

    async def scenario():
        first = RuntimeContext(policy=RuntimePolicy(deadline_seconds=0.03))
        task = asyncio.create_task(first.tool("first", "safe", blocking))
        while not entered.is_set():
            await asyncio.sleep(0.001)
        second = RuntimeContext(policy=RuntimePolicy(deadline_seconds=0.03))
        with pytest.raises(RunTimedOut):
            await second.tool("second", "safe", lambda: extra_calls.append(1))
        with pytest.raises(RunTimedOut):
            await task
        assert extra_calls == []
        release.set()
        await asyncio.sleep(0.02)

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_lazy_gateway_initialization_is_bounded(monkeypatch):
    from backend.agent import graph
    from backend.domain.user_preferences import UserPreferences

    monkeypatch.setattr(graph, "_resolve_gateway", lambda user_id: time.sleep(0.3))
    workflow = graph._LazyFitLifeWorkflow(object(), None, "u", UserPreferences())
    runtime = AgentRuntime(policy=RuntimePolicy(deadline_seconds=0.03))
    started = time.monotonic()
    with pytest.raises(RunTimedOut):
        runtime.execute_sync(AgentCommand("chat", "hello", "u"), workflow)
    assert time.monotonic() - started < 0.2


@pytest.mark.parametrize("protocol", ["responses", "chat"])
def test_worker_propagates_remaining_budget_to_sdk(protocol):
    from backend.infrastructure.model_gateway.openai_responses import OpenAIResponsesAdapter
    from backend.infrastructure.model_gateway.openai_chat_completions import OpenAIChatCompletionsAdapter

    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_text="ok", choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

    gateway = OpenAIResponsesAdapter(client=SimpleNamespace(responses=SimpleNamespace(create=create)), model="test")
    if protocol == "chat":
        gateway = OpenAIChatCompletionsAdapter(client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), model="test")
    context = RuntimeContext(policy=RuntimePolicy(deadline_seconds=0.5))
    time.sleep(0.03)
    assert asyncio.run(context.tool("writer_model", "safe", lambda: gateway.write_answer({}))) == "ok"
    assert 0 < calls[0]["timeout"] < 0.48
    gateway.write_answer({})
    assert "timeout" not in calls[1]


def test_sync_bridge_inside_running_loop_returns_at_deadline():
    class Workflow:
        async def execute(self, command, context):
            await context.tool("slow", "safe", lambda: time.sleep(0.3))

    async def scenario():
        runtime = AgentRuntime(policy=RuntimePolicy(deadline_seconds=0.03))
        started = time.monotonic()
        with pytest.raises(RunTimedOut):
            runtime.execute_sync(AgentCommand("chat", "hello", "u"), Workflow())
        assert time.monotonic() - started < 0.2

    asyncio.run(scenario())
