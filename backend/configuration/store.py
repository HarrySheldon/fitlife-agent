from threading import RLock
from typing import Protocol
from pydantic import ValidationError

from backend.configuration.models import RuntimePolicy, RunPolicySnapshot
from backend.configuration.diagnostics import OperatorDiagnostics


class PolicyStore(Protocol):
    def read(self) -> RunPolicySnapshot: ...
    def publish(self, candidate: dict) -> RunPolicySnapshot: ...


class MemoryPolicyStore:
    """Atomic in-process revision publication with last-known-good retention."""
    def __init__(self, diagnostics=None):
        self.diagnostics = diagnostics or OperatorDiagnostics()
        self._lock = RLock()
        self._current = RunPolicySnapshot()

    def read(self):
        with self._lock:
            return self._current

    def publish(self, candidate):
        try:
            policy = RuntimePolicy.model_validate(candidate)
        except (ValueError, TypeError):
            self.diagnostics.rejected(self.read().revision)
            raise ValueError("Runtime policy update rejected") from None
        with self._lock:
            self._current = RunPolicySnapshot(revision=self._current.revision + 1, policy=policy)
            return self._current
