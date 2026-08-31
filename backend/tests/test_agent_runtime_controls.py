from backend.agent.failures import Disposition, classify_failure, decide_disposition
import asyncio

import pytest

from backend.agent.contracts import AgentCommand, AgentResult
from backend.agent.policy import BudgetPolicy, RetryPolicy, RuntimePolicy
from backend.agent.runtime import AgentRuntime, BudgetExceeded, RunCancelled, RunTimedOut, RuntimeContext


class ProviderError(Exception):
    def __init__(self, status_code: int, *, code: str = "", retry_after: float | None = None):
        self.status_code = status_code
        self.code = code
        self.retry_after = retry_after


def test_runtime_policy_uses_three_retries_and_caps_provider_retry_after():
    policy = RuntimePolicy(retry=RetryPolicy(max_retries=3, max_delay_seconds=10))

    assert policy.retry.max_attempts == 4
    assert policy.retry.delay_seconds(1, retry_after=99, random_value=0.5) == 10


def test_failure_classification_retries_only_transient_provider_failures():
    retryable = [ConnectionError(), ProviderError(408), ProviderError(409, code="conflict"), ProviderError(429), ProviderError(503)]
    terminal = [ProviderError(401), ProviderError(403), ProviderError(404, code="model_not_found"), ProviderError(400), ProviderError(429, code="insufficient_quota")]

    assert all(decide_disposition(classify_failure(error, stage="model", attempt=1)) is Disposition.RETRY for error in retryable)
    assert all(decide_disposition(classify_failure(error, stage="model", attempt=1)) is not Disposition.RETRY for error in terminal)


def test_safe_operation_retries_but_never_replay_tool_does_not():
    attempts = 0
    async def flaky():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionError("temporary")
        return "ok"

    context = RuntimeContext(policy=RuntimePolicy(retry=RetryPolicy(base_delay_seconds=0)), sleeper=lambda _delay: asyncio.sleep(0))
    assert asyncio.run(context.tool("safe", "safe", flaky)) == "ok"
    assert attempts == 3

    attempts = 0
    with pytest.raises(ConnectionError):
        asyncio.run(context.tool("write", "never", flaky))
    assert attempts == 1


def test_budget_is_accumulated_and_enforced():
    context = RuntimeContext(policy=RuntimePolicy(budget=BudgetPolicy(max_input_chars=3, max_tokens=2, max_model_calls=1, max_tool_calls=1)))
    with pytest.raises(BudgetExceeded):
        context.consume_input("four")


def test_cancelled_run_has_ids_and_explicit_final_status():
    started = asyncio.Event()
    release = asyncio.Event()
    class Workflow:
        async def execute(self, command, context):
            started.set()
            await release.wait()
            context.raise_if_cancelled()

    async def scenario():
        runtime = AgentRuntime()
        task = asyncio.create_task(runtime.execute(AgentCommand("chat", "hello", "u"), Workflow()))
        await started.wait()
        run_id = next(iter(runtime.active_run_ids))
        result = await runtime.cancel(run_id, "u")
        release.set()
        with pytest.raises(RunCancelled) as raised:
            await task
        snapshot = await runtime.get_status(run_id, "u")
        return result, raised.value, snapshot

    result, error, snapshot = asyncio.run(scenario())
    assert result.cancelled is True
    assert error.request_id
    assert snapshot.status == "cancelled"


def test_overall_deadline_is_not_reset_between_retries():
    now = [0.0]
    async def advance(delay):
        now[0] += delay
    async def fail():
        raise ConnectionError("temporary")
    context = RuntimeContext(
        policy=RuntimePolicy(deadline_seconds=1.1, retry=RetryPolicy(base_delay_seconds=1, jitter_ratio=0)),
        clock=lambda: now[0], sleeper=advance,
    )

    with pytest.raises(RunTimedOut):
        asyncio.run(context.step("provider", fail))

    assert now[0] == 1


def test_cancellation_is_checked_immediately_after_retry_backoff():
    cancelled = asyncio.Event()
    async def cancel_during_wait(_delay):
        cancelled.set()
    context = RuntimeContext(
        policy=RuntimePolicy(retry=RetryPolicy(base_delay_seconds=0)),
        sleeper=cancel_during_wait,
        cancel_event=cancelled,
    )

    with pytest.raises(RunCancelled):
        asyncio.run(context.step("provider", lambda: (_ for _ in ()).throw(ConnectionError())))
