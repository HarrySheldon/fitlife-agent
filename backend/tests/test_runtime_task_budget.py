"""Scripted providers only; task accounting observes actual runtime attempts."""
import asyncio
from threading import Event
from types import SimpleNamespace

import pytest

from backend.agent.runtime import AgentRuntime, RuntimeContext, RunCancelled, RunTimedOut
from backend.agent.policy import RuntimePolicy, RetryPolicy


class Binding:
    user_id = 'alice'
    task_id = 'task'

    def __init__(self):
        self.reservations = []
        self.settlements = []
        self.on_reserve = lambda: None

    def reserve(self, *args):
        self.reservations.append(args)
        self.on_reserve()

    def settle(self, *args):
        self.settlements.append(args)


def test_retries_and_review_each_reserve_with_unique_ids():
    binding = Binding()
    attempts = 0
    async def provider():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError('scripted transient failure')
        return SimpleNamespace(usage={'total_tokens': 7})
    context = RuntimeContext(run_id='run', task_budget_binding=binding,
        policy=RuntimePolicy(retry=RetryPolicy(base_delay_seconds=0)))
    async def scenario():
        await context.tool('plan_route_model', 'safe', provider)
        await context.tool('safety_review_model', 'never', provider)
    asyncio.run(scenario())
    assert attempts == 3
    assert [row[0] for row in binding.reservations] == ['run:1', 'run:2', 'run:3']
    assert binding.settlements[0][-1] is False
    assert binding.settlements[1][2:] == (7, True)


def test_cancellation_after_reserve_never_enters_provider():
    binding = Binding()
    cancelled = Event()
    binding.on_reserve = cancelled.set
    calls = []
    context = RuntimeContext(run_id='run', cancel_event=cancelled, task_budget_binding=binding)
    with pytest.raises(RunCancelled):
        asyncio.run(context.tool('write_answer_model', 'safe', lambda: calls.append(1)))
    assert calls == []
    assert binding.settlements[0][-1] is False


def test_unknown_usage_and_callback_failure_never_replay_provider():
    binding = Binding()
    calls = []
    async def provider():
        calls.append(1)
        return SimpleNamespace(usage={})
    context = RuntimeContext(run_id='run', task_budget_binding=binding)
    asyncio.run(context.tool('write_answer_model', 'safe', provider))
    assert binding.settlements[0][2:] == (context.policy.budget.max_tokens, False)
    def fail(*args):
        raise ConnectionError('scripted accounting failure')
    binding.settle = fail
    with pytest.raises(ConnectionError):
        asyncio.run(context.tool('write_answer_model', 'safe', provider))
    assert len(calls) == 2


def test_timeout_retains_charge_and_late_provider_return_is_discarded():
    binding = Binding()
    release = Event()
    entered = Event()
    returned = Event()
    def provider():
        entered.set()
        release.wait(2)
        returned.set()
        return SimpleNamespace(usage={'total_tokens': 1})
    context = RuntimeContext(run_id='run', task_budget_binding=binding,
        policy=RuntimePolicy(deadline_seconds=0.05))
    try:
        with pytest.raises(RunTimedOut):
            asyncio.run(context.tool('write_answer_model', 'safe', provider))
        assert entered.is_set()
    finally:
        release.set()
    assert returned.wait(1)
    assert len(binding.settlements) == 1
    assert binding.settlements[0][-1] is False
    assert context.completed_tools == []


def test_untasked_runtime_never_calls_binding_factory():
    from backend.agent.contracts import AgentCommand, AgentResult
    class Workflow:
        async def execute(self, command, context):
            assert context.task_budget_binding is None
            return AgentResult('A balanced meal can help.', 'chat', {}, {}, (), 'mock')
    def forbidden(*args):
        raise AssertionError('untasked run touched task budgets')
    asyncio.run(AgentRuntime(task_budget_binding_factory=forbidden).execute(
        AgentCommand('chat', 'hello', 'alice'), Workflow()))


def test_task_factory_persists_spend_across_runs_including_reviewer(tmp_path):
    from backend.agent.contracts import AgentCommand, AgentResult
    from backend.agent.tasks.contracts import TaskRef
    from backend.agent.runtime import TaskBudgetExceeded
    from backend.application.ports.task_budget_repository import TaskBudgetBinding
    from backend.infrastructure.sqlite.database import SQLiteDatabase
    from backend.infrastructure.sqlite.migrations import run_migrations
    from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS
    from backend.infrastructure.repositories.sqlite_task_budget_repository import SQLiteTaskBudgetRepository
    database = SQLiteDatabase(tmp_path / 'runtime.sqlite')
    run_migrations(database, RECORDS_MIGRATIONS)
    repository = SQLiteTaskBudgetRepository(database)
    repository.initialize('alice', 'task', 3, 100000)
    calls = []
    async def provider():
        calls.append(1)
        return SimpleNamespace(usage={'input_tokens': 2, 'output_tokens': 3})
    class Workflow:
        async def execute(self, command, context):
            await context.tool('write_answer_model', 'safe', provider)
            await context.tool('safety_review_model', 'safe', provider)
            return AgentResult('A balanced meal can help.', 'chat', {}, {}, (), 'mock')
    def factory(owner, ref):
        assert (owner, ref) == ('alice', TaskRef('task', 1))
        return TaskBudgetBinding(repository, owner, ref.task_id)
    runtime = AgentRuntime(task_budget_binding_factory=factory)
    command = AgentCommand('chat', 'hello', 'alice', task_ref=TaskRef('task', 1))
    asyncio.run(runtime.execute(command, Workflow()))
    assert repository.get_snapshot('alice', 'task').spent_calls == 2
    with pytest.raises(TaskBudgetExceeded):
        asyncio.run(runtime.execute(command, Workflow()))
    assert len(calls) == 3
    snapshot = repository.get_snapshot('alice', 'task')
    assert (snapshot.spent_calls, snapshot.spent_tokens) == (3, 15)


def test_binding_factory_owner_mismatch_fails_before_provider():
    from backend.agent.contracts import AgentCommand
    from backend.agent.tasks.contracts import TaskRef
    class Workflow:
        async def execute(self, command, context):
            raise AssertionError('mismatched binding entered workflow')
    binding = Binding()
    binding.user_id = 'bob'
    runtime = AgentRuntime(task_budget_binding_factory=lambda owner, ref: binding)
    with pytest.raises(ValueError, match='trusted command'):
        asyncio.run(runtime.execute(AgentCommand('chat', 'hello', 'alice', task_ref=TaskRef('task', 1)), Workflow()))


def test_settlement_failure_preserves_cancellation_and_timeout():
    for error_type in (RunCancelled, RunTimedOut):
        binding = Binding()
        def fail(*args):
            raise ConnectionError('accounting unavailable')
        binding.settle = fail
        async def provider():
            raise error_type('terminal control condition')
        context = RuntimeContext(task_budget_binding=binding)
        with pytest.raises(error_type):
            asyncio.run(context.tool('write_answer_model', 'safe', provider))
        assert len(binding.reservations) == 1


def test_late_return_never_changes_terminal_runtime_snapshot():
    from backend.agent.contracts import AgentCommand
    from backend.agent.tasks.contracts import TaskRef
    binding = Binding()
    release = Event()
    returned = Event()
    def provider():
        release.wait(2)
        returned.set()
        return SimpleNamespace(usage={'total_tokens': 1})
    class Workflow:
        async def execute(self, command, context):
            return await context.tool('write_answer_model', 'safe', provider)
    runtime = AgentRuntime(policy=RuntimePolicy(deadline_seconds=0.05),
        task_budget_binding_factory=lambda owner, ref: binding)
    async def scenario():
        try:
            await runtime.execute(AgentCommand('chat', 'hello', 'alice', task_ref=TaskRef('task', 1)), Workflow())
        except RunTimedOut as error:
            before = await runtime.get_status(error.run_id, 'alice')
            release.set()
            # The thread can finish, but cannot publish into terminal state.
            while not returned.is_set():
                await asyncio.sleep(0.001)
            await asyncio.sleep(0.01)
            after = await runtime.get_status(error.run_id, 'alice')
            return before, after
        finally:
            release.set()
        raise AssertionError('expected timeout')
    before, after = asyncio.run(scenario())
    assert before.status == after.status == 'timed_out'
    assert before.version == after.version
    assert len(binding.settlements) == 1
    assert binding.settlements[0][-1] is False


def test_total_provider_usage_includes_already_consumed_context(tmp_path):
    from backend.agent.policy import BudgetPolicy
    from backend.application.ports.task_budget_repository import TaskBudgetBinding
    from backend.infrastructure.sqlite.database import SQLiteDatabase
    from backend.infrastructure.sqlite.migrations import run_migrations
    from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS
    from backend.infrastructure.repositories.sqlite_task_budget_repository import SQLiteTaskBudgetRepository
    database = SQLiteDatabase(tmp_path / 'input-inclusive.sqlite')
    run_migrations(database, RECORDS_MIGRATIONS)
    repository = SQLiteTaskBudgetRepository(database)
    repository.initialize('alice', 'task', 1, 100)
    context = RuntimeContext(task_budget_binding=TaskBudgetBinding(repository, 'alice', 'task'),
        policy=RuntimePolicy(budget=BudgetPolicy(max_tokens=100)), token_estimator=lambda text: 80)
    context.consume_context('already consumed input')
    async def provider():
        return SimpleNamespace(usage={'input_tokens': 80, 'output_tokens': 10})
    asyncio.run(context.tool('write_answer_model', 'safe', provider))
    assert repository.get_snapshot('alice', 'task').spent_tokens == 90


def test_successful_provider_settlement_failure_preserves_new_control_condition():
    for error_type in (RunCancelled, RunTimedOut):
        binding = Binding()
        cancelled = Event()
        now = [0.0]
        def fail(*args):
            if error_type is RunCancelled:
                cancelled.set()
            else:
                now[0] = 2.0
            raise ConnectionError('accounting unavailable after provider returned')
        binding.settle = fail
        context = RuntimeContext(task_budget_binding=binding, cancel_event=cancelled,
            clock=lambda: now[0], deadline_at=1.0)
        async def provider():
            return SimpleNamespace(usage={'total_tokens': 1})
        with pytest.raises(error_type):
            asyncio.run(context.tool('write_answer_model', 'safe', provider))
        assert len(binding.reservations) == 1


def test_provider_failure_settlement_failure_preserves_new_control_condition():
    for error_type in (RunCancelled, RunTimedOut):
        binding = Binding()
        cancelled = Event()
        now = [0.0]
        def fail(*args):
            if error_type is RunCancelled:
                cancelled.set()
            else:
                now[0] = 2.0
            raise ConnectionError('accounting unavailable after provider failed')
        binding.settle = fail
        context = RuntimeContext(task_budget_binding=binding, cancel_event=cancelled,
            clock=lambda: now[0], deadline_at=1.0)
        async def provider():
            raise ConnectionError('scripted provider failure')
        with pytest.raises(error_type):
            asyncio.run(context.tool('write_answer_model', 'safe', provider))
        assert len(binding.reservations) == 1
