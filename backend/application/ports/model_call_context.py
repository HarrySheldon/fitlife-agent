"""Per-run transport budget, propagated across synchronous worker boundaries."""
from collections.abc import Callable
from contextvars import ContextVar

remaining_model_timeout: ContextVar[Callable[[], float] | None] = ContextVar(
    "remaining_model_timeout", default=None
)


def model_timeout_options() -> dict[str, float]:
    remaining = remaining_model_timeout.get()
    return {"timeout": remaining()} if remaining is not None else {}
