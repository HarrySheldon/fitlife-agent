"""Durable conservative reservations; abandoned reservations continue consuming quota."""
from backend.application.ports.task_budget_repository import TaskBudgetConflict, TaskBudgetSnapshot
from backend.infrastructure.sqlite.database import SQLiteDatabase


def _counts(*values):
    if any(type(value) is not int or not 0 <= value <= 9223372036854775807 for value in values):
        raise ValueError('Budget counts must be nonnegative integers')


def _identity(*values):
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError('Budget identity is required')


class SQLiteTaskBudgetRepository:
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    def initialize(self, user_id, task_id, call_limit, token_limit):
        _identity(user_id, task_id)
        _counts(call_limit, token_limit)
        with self.database.transaction() as connection:
            row = connection.execute('SELECT * FROM task_budgets WHERE user_id=? AND task_id=?', (user_id, task_id)).fetchone()
            if row is not None and (row['call_limit'], row['token_limit']) != (call_limit, token_limit):
                raise TaskBudgetConflict('Budget limits are immutable')
            connection.execute('INSERT OR IGNORE INTO task_budgets(user_id,task_id,call_limit,token_limit) VALUES (?,?,?,?)', (user_id, task_id, call_limit, token_limit))
            return self._snapshot(connection, user_id, task_id)

    create = initialize

    def reserve(self, user_id, task_id, operation_id, calls, tokens):
        _identity(user_id, task_id, operation_id)
        _counts(calls, tokens)
        with self.database.transaction() as connection:
            snapshot = self._snapshot(connection, user_id, task_id)
            row = self._operation(connection, user_id, task_id, operation_id)
            if row is not None:
                if (row['calls'], row['tokens']) != (calls, tokens):
                    raise TaskBudgetConflict('Reservation payload differs')
                return
            breached = connection.execute(
                'SELECT 1 FROM task_budget_operations WHERE user_id=? AND task_id=? AND usage_known=1 AND (actual_calls>calls OR actual_tokens>tokens) LIMIT 1',
                (user_id, task_id),
            ).fetchone()
            if breached is not None:
                from backend.agent.runtime import TaskBudgetExceeded
                raise TaskBudgetExceeded('A provider exceeded its task reservation.')
            if snapshot.spent_calls + snapshot.reserved_calls + calls > snapshot.call_limit or snapshot.spent_tokens + snapshot.reserved_tokens + tokens > snapshot.token_limit:
                from backend.agent.runtime import TaskBudgetExceeded
                raise TaskBudgetExceeded('The task budget was exhausted.')
            connection.execute('INSERT INTO task_budget_operations(user_id,task_id,operation_id,calls,tokens) VALUES (?,?,?,?,?)', (user_id, task_id, operation_id, calls, tokens))

    def settle(self, user_id, task_id, operation_id, actual_calls, actual_tokens, usage_known):
        _identity(user_id, task_id, operation_id)
        _counts(actual_calls, actual_tokens)
        if type(usage_known) is not bool:
            raise ValueError('usage_known must be boolean')
        overrun = False
        with self.database.transaction() as connection:
            self._snapshot(connection, user_id, task_id)
            row = self._operation(connection, user_id, task_id, operation_id)
            if row is None:
                raise KeyError(operation_id)
            payload = (actual_calls, actual_tokens, int(usage_known))
            if row['usage_known'] is not None:
                if (row['actual_calls'], row['actual_tokens'], row['usage_known']) != payload:
                    raise TaskBudgetConflict('Settlement payload differs')
                return
            # Known billable usage must remain truthful even beyond a ceiling.
            # Persist it first, then fail the run and block further reservations.
            overrun = usage_known and (actual_calls > row['calls'] or actual_tokens > row['tokens'])
            connection.execute('UPDATE task_budget_operations SET actual_calls=?,actual_tokens=?,usage_known=? WHERE user_id=? AND task_id=? AND operation_id=?', (*payload, user_id, task_id, operation_id))
        if overrun:
            from backend.agent.runtime import TaskBudgetExceeded
            raise TaskBudgetExceeded('A provider exceeded its task reservation.')

    def get_snapshot(self, user_id, task_id):
        _identity(user_id, task_id)
        with self.database.transaction() as connection:
            return self._snapshot(connection, user_id, task_id)

    @staticmethod
    def _operation(connection, user_id, task_id, operation_id):
        return connection.execute('SELECT * FROM task_budget_operations WHERE user_id=? AND task_id=? AND operation_id=?', (user_id, task_id, operation_id)).fetchone()

    @staticmethod
    def _snapshot(connection, user_id, task_id):
        budget = connection.execute('SELECT * FROM task_budgets WHERE user_id=? AND task_id=?', (user_id, task_id)).fetchone()
        if budget is None:
            raise KeyError(task_id)
        rows = connection.execute('SELECT * FROM task_budget_operations WHERE user_id=? AND task_id=?', (user_id, task_id)).fetchall()
        spent_calls = spent_tokens = reserved_calls = reserved_tokens = 0
        for row in rows:
            if row['usage_known'] is None:
                reserved_calls += row['calls']; reserved_tokens += row['tokens']
            else:
                spent_calls += row['actual_calls'] if row['usage_known'] else row['calls']
                spent_tokens += row['actual_tokens'] if row['usage_known'] else row['tokens']
        return TaskBudgetSnapshot(budget['call_limit'], budget['token_limit'], spent_calls, spent_tokens, reserved_calls, reserved_tokens)
