"""Explicit maintenance operation. Preview by default; no database discovery."""
from contextlib import AbstractContextManager, nullcontext
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from backend.application.ports.entry_task_lifecycle import EntryTaskExpiryPort


@dataclass(frozen=True)
class ExpiredAgentTasks:
    task_ids: tuple[str, ...]
    dry_run: bool

    @property
    def count(self) -> int:
        return len(self.task_ids)


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('An aware timestamp is required')
    return value.astimezone(timezone.utc)


class ExpireAgentTasks:
    def __init__(self, repository: EntryTaskExpiryPort, *, clock: Callable[[], datetime] | None = None,
                 mutation_scope: Callable[[str], AbstractContextManager] | None = None):
        self.repository = repository
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.mutation_scope = mutation_scope or (lambda _user: nullcontext())

    def execute(self, user_id: str, *, cutoff: datetime, dry_run: bool = True) -> ExpiredAgentTasks:
        if not isinstance(user_id, str) or not user_id.strip() or type(dry_run) is not bool:
            raise ValueError('Explicit owner and boolean dry_run are required')
        cutoff = _utc(cutoff)
        if cutoff > _utc(self.clock()):
            raise ValueError('Cutoff cannot be in the future')
        with self.mutation_scope(user_id) if not dry_run else nullcontext():
            ids = self.repository.expire_tasks(user_id, cutoff=cutoff, dry_run=dry_run)
        return ExpiredAgentTasks(ids, dry_run)
