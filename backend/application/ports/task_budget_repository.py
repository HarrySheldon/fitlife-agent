"""Owner-scoped accounting. Only trusted application code supplies owner/task IDs.

Each runtime attempt holds the full run token ceiling because provider total
usage includes input already consumed by the runtime. Unknown usage spends the
whole reservation; an abandoned attempt retains its hold. Known usage beyond a
reservation is persisted truthfully (spent may exceed limits), then exhausts the
task for new attempts. Repeating identical callbacks never changes accounting.
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TaskBudgetSnapshot:
    call_limit: int
    token_limit: int
    spent_calls: int
    spent_tokens: int
    reserved_calls: int
    reserved_tokens: int


class TaskBudgetConflict(ValueError):
    code = 'IDEMPOTENCY_CONFLICT'


class TaskBudgetRepository(Protocol):
    def initialize(self, user_id: str, task_id: str, call_limit: int, token_limit: int) -> TaskBudgetSnapshot: ...
    def reserve(self, user_id: str, task_id: str, operation_id: str, calls: int, tokens: int) -> None: ...
    def settle(self, user_id: str, task_id: str, operation_id: str, actual_calls: int, actual_tokens: int, usage_known: bool) -> None: ...
    def get_snapshot(self, user_id: str, task_id: str) -> TaskBudgetSnapshot: ...


@dataclass(frozen=True)
class TaskBudgetBinding:
    repository: TaskBudgetRepository
    user_id: str
    task_id: str

    def reserve(self, operation_id: str, calls: int, tokens: int) -> None:
        try:
            self.repository.reserve(self.user_id, self.task_id, operation_id, calls, tokens)
        except KeyError:
            from backend.agent.tasks.contracts import task_error
            raise task_error('TASK_NOT_FOUND') from None

    def settle(self, operation_id: str, actual_calls: int, actual_tokens: int, usage_known: bool) -> None:
        try:
            self.repository.settle(self.user_id, self.task_id, operation_id, actual_calls, actual_tokens, usage_known)
        except KeyError:
            from backend.agent.tasks.contracts import task_error
            raise task_error('TASK_NOT_FOUND') from None
