"""Per-run transport budget and cancellation, propagated across thread boundaries.

``remaining_model_timeout`` and ``model_output_limit`` are read where the model is
called. ``current_abort`` is different: it carries a mutable registry that a
*canceller* — usually another thread — can fire. The registry is deliberately an
object rather than a plain value so copying the context (which happens when work
moves into a worker thread) shares it instead of duplicating it.
"""
from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from threading import Lock

remaining_model_timeout: ContextVar[Callable[[], float] | None] = ContextVar(
    "remaining_model_timeout", default=None
)
model_output_limit: ContextVar[int | None] = ContextVar("model_output_limit", default=None)


def model_timeout_options() -> dict[str, float]:
    remaining = remaining_model_timeout.get()
    return {"timeout": remaining()} if remaining is not None else {}


class AbortRegistry:
    """Closable resources belonging to one run, closed at most once.

    A cancel that only flips a flag leaves the synchronous model thread alive,
    holding a socket and a slot until the provider answers. Registering the
    gateway's ``close`` makes cancellation close the transport itself, so the
    worker exits instead of lingering.

    Hooks must be idempotent and must not block for long. ``abort`` is safe to
    call from any thread, including while another thread is registering.
    """

    def __init__(self) -> None:
        self._hooks: list[Callable[[], None]] = []
        self._aborted = False
        self._lock = Lock()

    @property
    def aborted(self) -> bool:
        with self._lock:
            return self._aborted

    def register(self, hook: Callable[[], None]) -> None:
        """Register a resource. If the run is already aborting, close it now."""
        with self._lock:
            if not self._aborted:
                self._hooks.append(hook)
                return
        _close_quietly(hook)

    def abort(self) -> int:
        """Close every registered resource. Returns how many were closed."""
        with self._lock:
            if self._aborted:
                return 0
            self._aborted = True
            hooks, self._hooks = self._hooks, []
        for hook in hooks:
            _close_quietly(hook)
        return len(hooks)


def _close_quietly(hook: Callable[[], None]) -> None:
    try:
        hook()
    except Exception:
        # A failed close must not stop the remaining closes, and must not replace
        # the cancellation the caller asked for.
        pass


current_abort: ContextVar[AbortRegistry | None] = ContextVar("current_abort", default=None)
