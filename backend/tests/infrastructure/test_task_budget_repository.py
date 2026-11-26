from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.infrastructure.repositories.postgres_task_budget_repository import PostgresTaskBudgetRepository
from backend.application.ports.task_budget_repository import TaskBudgetConflict


def test_last_slot_is_atomic_and_duplicate_operations_are_free(pg_db):
    repository = PostgresTaskBudgetRepository(pg_db)
    repository.initialize('alice', 'task', 1, 10)
    def reserve(operation):
        try:
            repository.reserve('alice', 'task', operation, 1, 10)
            return operation
        except Exception as error:
            assert error.code == 'TASK_BUDGET_EXHAUSTED'
    with ThreadPoolExecutor(max_workers=2) as executor:
        winners = [value for value in executor.map(reserve, ['one', 'two']) if value]
    assert len(winners) == 1
    operation = winners[0]
    repository.reserve('alice', 'task', operation, 1, 10)
    repository.settle('alice', 'task', operation, 1, 4, True)
    repository.settle('alice', 'task', operation, 1, 4, True)
    snapshot = repository.get_snapshot('alice', 'task')
    assert (snapshot.spent_calls, snapshot.spent_tokens, snapshot.reserved_tokens) == (1, 4, 0)
    with pytest.raises(KeyError):
        repository.get_snapshot('bob', 'task')


def test_crash_unknown_usage_and_conflicts_preserve_charge(pg_db):
    repository = PostgresTaskBudgetRepository(pg_db)
    repository.initialize('alice', 'task', 3, 30)
    repository.reserve('alice', 'task', 'crashed', 1, 10)
    repository = PostgresTaskBudgetRepository(pg_db)
    assert repository.get_snapshot('alice', 'task').reserved_tokens == 10
    repository.reserve('alice', 'task', 'unknown', 1, 10)
    repository.settle('alice', 'task', 'unknown', 0, 0, False)
    repository.settle('alice', 'task', 'unknown', 0, 0, False)
    snapshot = repository.get_snapshot('alice', 'task')
    assert (snapshot.spent_calls, snapshot.spent_tokens) == (1, 10)
    with pytest.raises(TaskBudgetConflict):
        repository.settle('alice', 'task', 'unknown', 1, 2, True)
    with pytest.raises(TaskBudgetConflict):
        repository.reserve('alice', 'task', 'unknown', 1, 9)
    with pytest.raises(TaskBudgetConflict):
        repository.initialize('alice', 'task', 4, 30)
    for value in (True, -1, 1.5, 2**63):
        with pytest.raises(ValueError):
            repository.reserve('alice', 'task', 'bad', value, 0)
    from backend.agent.runtime import TaskBudgetExceeded
    with pytest.raises(TaskBudgetExceeded):
        repository.settle('alice', 'task', 'crashed', 1, 31, True)
    snapshot = repository.get_snapshot('alice', 'task')
    assert (snapshot.spent_tokens, snapshot.reserved_tokens) == (41, 0)
    repository.settle('alice', 'task', 'crashed', 1, 31, True)
    with pytest.raises(TaskBudgetExceeded):
        repository.reserve('alice', 'task', 'after-overrun', 1, 0)


def test_account_delete_removes_only_owned_budget(pg_db):
    from backend.infrastructure.repositories.postgres_profile_target_repository import PostgresProfileTargetRepository
    repository = PostgresTaskBudgetRepository(pg_db)
    for owner in ('alice', 'bob'):
        repository.initialize(owner, 'task', 2, 20)
        repository.reserve(owner, 'task', 'one', 1, 10)
    PostgresProfileTargetRepository(pg_db).delete_user_data('alice')
    with pytest.raises(KeyError):
        repository.get_snapshot('alice', 'task')
    assert repository.get_snapshot('bob', 'task').reserved_calls == 1
