"""Optional, content-free diagnostics, separate from authoritative run events."""
from __future__ import annotations

import asyncio
import math
import re
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import RLock
from typing import Protocol
from uuid import uuid4

Scalar = str | int | float | bool
_SPAN_NAMES = frozenset({
    "fitlife.agent.run", "fitlife.agent.step", "fitlife.ai.request",
    "fitlife.agent.tool", "fitlife.agent.retry_wait", "fitlife.safety.review",
})
_METRICS = frozenset({"input_tokens", "output_tokens", "tool_calls", "model_calls", "attempt", "retry_count", "delay_ms"})
_LABELS = frozenset({"policy_version", "error_code", "step", "operation", "outcome"})


def _safe_attributes(attributes: Mapping[str, object]) -> dict[str, Scalar]:
    result: dict[str, Scalar] = {}
    for key, value in attributes.items():
        if key in _METRICS and type(value) in (int, float):
            if value >= 0 and math.isfinite(value):
                result[key] = value
        elif key in _LABELS and isinstance(value, str):
            if re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", value):
                result[key] = value
    return result


class TelemetryContext(Protocol):
    def span(self, name: str, attributes: Mapping[str, Scalar]) -> AbstractAsyncContextManager[object]: ...


class NoopTelemetryContext:
    @asynccontextmanager
    async def span(self, name: str, attributes: Mapping[str, Scalar]) -> AsyncIterator[None]:
        yield


class SafeSpan:
    def __init__(self, handle: object = None) -> None:
        self.handle = handle

    def set_attributes(self, attributes: Mapping[str, object]) -> None:
        try:
            setter = getattr(self.handle, "set_attributes", None)
            if setter is not None:
                setter(_safe_attributes(attributes))
        except Exception:
            pass


class SafeTelemetryContext:
    """Isolate adapter errors, while always propagating the original business error."""

    def __init__(self, adapter: TelemetryContext | None = None) -> None:
        self.adapter = adapter or NoopTelemetryContext()

    @asynccontextmanager
    async def span(self, name: str, attributes: Mapping[str, object]) -> AsyncIterator[SafeSpan]:
        manager = None
        entered = False
        handle = None
        try:
            if name in _SPAN_NAMES:
                manager = self.adapter.span(name, _safe_attributes(attributes))
                handle = await manager.__aenter__()
                entered = True
        except Exception:
            # Telemetry is never the authority for business success or failure.
            pass

        try:
            yield SafeSpan(handle)
        except BaseException as error:
            if entered:
                try:
                    diagnostic = (
                        asyncio.CancelledError()
                        if isinstance(error, asyncio.CancelledError) or getattr(error, "code", None) == "RUN_CANCELLED"
                        else RuntimeError("operation_failed")
                    )
                    await manager.__aexit__(type(diagnostic), diagnostic, None)
                except Exception:
                    pass
            raise
        else:
            if entered:
                try:
                    await manager.__aexit__(None, None, None)
                except Exception:
                    pass


@dataclass
class RecordedSpan:
    span_id: str
    parent_id: str | None
    name: str
    attributes: dict[str, Scalar]
    outcome: str = "running"
    duration_ms: float = 0

    def set_attributes(self, attributes: Mapping[str, Scalar]) -> None:
        self.attributes.update(_safe_attributes(attributes))


class InMemoryTelemetryContext:
    """Test adapter: parentage is isolated per asynchronous execution context."""

    def __init__(self, *, clock=time.monotonic) -> None:
        self.clock = clock
        self.spans: list[RecordedSpan] = []
        self._parent: ContextVar[str | None] = ContextVar("telemetry_parent", default=None)
        self._lock = RLock()

    @asynccontextmanager
    async def span(self, name: str, attributes: Mapping[str, Scalar]) -> AsyncIterator[RecordedSpan]:
        span = RecordedSpan(uuid4().hex, self._parent.get(), name, _safe_attributes(attributes))
        with self._lock:
            self.spans.append(span)
        parent_token = self._parent.set(span.span_id)
        started = self.clock()
        try:
            yield span
        except BaseException as error:
            span.outcome = "cancelled" if isinstance(error, asyncio.CancelledError) or getattr(error, "code", None) == "RUN_CANCELLED" else "failed"
            raise
        else:
            span.outcome = "succeeded"
        finally:
            span.duration_ms = max(0, (self.clock() - started) * 1000)
            self._parent.reset(parent_token)
