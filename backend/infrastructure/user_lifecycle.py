from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

from backend.domain.errors import ApplicationError


@dataclass
class _UserLifecycleState:
    lock: threading.RLock = field(default_factory=threading.RLock)
    deleted: bool = False


_STATES: dict[tuple[Path, str], _UserLifecycleState] = {}
_STATES_GUARD = threading.Lock()


class UserLifecycleGuard:
    def __init__(self, data_dir: Path, user_id: str) -> None:
        self._state = _state_for(data_dir, user_id)

    def __enter__(self) -> UserLifecycleGuard:
        self._state.lock.acquire()
        if self._state.deleted:
            self._state.lock.release()
            raise _token_invalid()
        return self

    def mark_deleted(self) -> None:
        self._state.deleted = True

    def __exit__(self, _error_type, _error, _traceback) -> None:
        self._state.lock.release()


def user_lifecycle_guard(data_dir: Path, user_id: str) -> UserLifecycleGuard:
    return UserLifecycleGuard(data_dir, user_id)


def _state_for(data_dir: Path, user_id: str) -> _UserLifecycleState:
    key = (Path(data_dir).resolve(), user_id)
    with _STATES_GUARD:
        return _STATES.setdefault(key, _UserLifecycleState())


def _token_invalid() -> ApplicationError:
    return ApplicationError(
        code="AUTH_TOKEN_INVALID",
        message="The session is invalid or has expired.",
        status_code=401,
    )
