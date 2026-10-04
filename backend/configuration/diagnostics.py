from collections import deque
from dataclasses import dataclass
from threading import RLock


@dataclass(frozen=True)
class ConfigurationDiagnostic:
    code: str
    revision: int


class OperatorDiagnostics:
    """Bounded diagnostics never retain validation input, paths, or exceptions."""
    def __init__(self):
        self._entries = deque(maxlen=100)
        self._lock = RLock()

    @property
    def entries(self):
        with self._lock:
            return tuple(self._entries)

    def rejected(self, revision):
        with self._lock:
            self._entries.append(ConfigurationDiagnostic("POLICY_UPDATE_REJECTED", revision))
