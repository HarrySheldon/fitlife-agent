"""Owner-scoped lifecycle seams; export never grants task access or runs models."""
from datetime import datetime
from typing import Protocol


class EntryTaskExportPort(Protocol):
    def export_entry_tasks(self, user_id: str, *, max_bytes: int) -> bytes: ...


class EntryTaskExpiryPort(Protocol):
    def expire_tasks(self, user_id: str, *, cutoff: datetime, dry_run: bool) -> tuple[str, ...]: ...
