"""OpenTelemetry and Langfuse OTLP trace context adapters.

All span attributes pass through ``backend.agent.telemetry._safe_attributes`` before
leaving this boundary, so raw user questions, medical notes, drafts, and secrets
are never emitted to external telemetry backends.
"""
from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import RLock
from typing import Any

from backend.agent.telemetry import (
    NoopTelemetryContext,
    Scalar,
    TelemetryContext,
    _safe_attributes,
    bind_trace_id,
    reset_trace_id,
)

_PROVIDER_LOCK = RLock()
_MANAGED_PROVIDERS: list[Any] = []


@dataclass(frozen=True)
class LangfuseOtlpConfig:
    endpoint: str
    headers: dict[str, str]

    @property
    def has_auth(self) -> bool:
        return "Authorization" in self.headers


def parse_otlp_headers(raw: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if not raw or not isinstance(raw, str):
        return headers
    for part in raw.split(","):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        cleaned_key = key.strip()
        cleaned_value = value.strip()
        if cleaned_key and cleaned_value:
            headers[cleaned_key] = cleaned_value
    return headers


def build_langfuse_otlp_config(
    *,
    host: str | None,
    public_key: str | None,
    secret_key: str | None,
    endpoint_override: str | None = None,
    extra_headers: str | None = None,
) -> LangfuseOtlpConfig | None:
    endpoint = (endpoint_override or "").strip()
    if not endpoint:
        base = (host or "").strip().rstrip("/")
        if not base:
            return None
        endpoint = f"{base}/api/public/otel/v1/traces"

    headers = parse_otlp_headers(extra_headers)
    if public_key and secret_key:
        token = base64.b64encode(f"{public_key}:{secret_key}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    if "Authorization" not in headers:
        return None
    return LangfuseOtlpConfig(endpoint=endpoint, headers=headers)


class OtelSpanHandle:
    def __init__(self, span: Any) -> None:
        self._span = span

    @property
    def trace_id(self) -> str:
        ctx = self._span.get_span_context()
        return f"{ctx.trace_id:032x}" if getattr(ctx, "trace_id", 0) else ""

    def set_attributes(self, attributes: Mapping[str, object]) -> None:
        safe = _safe_attributes(attributes)
        if safe:
            self._span.set_attributes(safe)


class OtelTelemetryContext:
    """Content-free OpenTelemetry tracer adapter with ContextVar parent isolation."""

    def __init__(
        self,
        *,
        provider: Any,
        tracer_name: str = "fitlife.agent",
        exporter: Any = None,
        memory_exporter: Any = None,
        exporter_kind: str = "otlp",
        exporter_endpoint: str | None = None,
    ) -> None:
        self._provider = provider
        self._tracer = provider.get_tracer(tracer_name)
        self._exporter = exporter
        self._memory_exporter = memory_exporter
        self.exporter_kind = exporter_kind
        self.exporter_endpoint = exporter_endpoint
        self._active_span: ContextVar[Any | None] = ContextVar("otel_active_span", default=None)

    def finished_spans(self) -> tuple[Any, ...]:
        if self._memory_exporter is None:
            return ()
        return tuple(self._memory_exporter.get_finished_spans())

    def force_flush(self, timeout_millis: int = 2000) -> bool:
        fn = getattr(self._provider, "force_flush", None)
        if callable(fn):
            return bool(fn(timeout_millis))
        return True

    def shutdown(self) -> None:
        with _PROVIDER_LOCK:
            try:
                _MANAGED_PROVIDERS.remove(self._provider)
            except ValueError:
                pass
        try:
            self._provider.force_flush(2000)
        except Exception:
            pass
        try:
            self._provider.shutdown()
        except Exception:
            pass

    @asynccontextmanager
    async def span(self, name: str, attributes: Mapping[str, Scalar]) -> AsyncIterator[OtelSpanHandle]:
        with self.sync_span(name, attributes) as handle:
            yield handle

    @contextmanager
    def sync_span(self, name: str, attributes: Mapping[str, Scalar]) -> Iterator[OtelSpanHandle]:
        from opentelemetry.context import Context
        from opentelemetry.trace import Status, StatusCode, set_span_in_context

        parent_span = self._active_span.get()
        parent_ctx = set_span_in_context(parent_span) if parent_span is not None else Context()
        otel_span = self._tracer.start_span(
            name,
            context=parent_ctx,
            attributes=_safe_attributes(attributes),
        )
        handle = OtelSpanHandle(otel_span)
        span_token = self._active_span.set(otel_span)
        trace_token = bind_trace_id(handle.trace_id or None)
        try:
            yield handle
        except BaseException as error:
            is_cancelled = isinstance(error, asyncio.CancelledError) or getattr(error, "code", None) == "RUN_CANCELLED"
            otel_span.set_status(Status(StatusCode.ERROR, "cancelled" if is_cancelled else "operation_failed"))
            raise
        else:
            otel_span.set_status(Status(StatusCode.OK))
        finally:
            otel_span.end()
            reset_trace_id(trace_token)
            self._active_span.reset(span_token)


def build_telemetry_context(settings: Any = None) -> TelemetryContext:
    """Create the configured telemetry adapter, failing safely to Noop on missing config."""
    if settings is None:
        from backend.config import get_settings

        settings = get_settings()

    kind = getattr(settings, "telemetry_exporter", "none") or "none"
    if kind == "none":
        return NoopTelemetryContext()

    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    except ImportError:
        return NoopTelemetryContext()

    service_name = getattr(settings, "otel_service_name", None) or "fitlife-agent"
    provider = TracerProvider(resource=Resource.create({"service.name": str(service_name)}))

    if kind == "memory":
        mem_exporter = InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(mem_exporter))
        _register_provider(provider)
        return OtelTelemetryContext(
            provider=provider,
            exporter=mem_exporter,
            memory_exporter=mem_exporter,
            exporter_kind="memory",
        )

    if kind == "otlp":
        endpoint = (getattr(settings, "otel_exporter_otlp_endpoint", None) or "").strip()
        if not endpoint:
            return NoopTelemetryContext()
        headers = parse_otlp_headers(getattr(settings, "otel_exporter_otlp_headers", None))
        exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers or None)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        _register_provider(provider)
        return OtelTelemetryContext(
            provider=provider,
            exporter=exporter,
            exporter_kind="otlp",
            exporter_endpoint=endpoint,
        )

    if kind == "langfuse":
        cfg = build_langfuse_otlp_config(
            host=getattr(settings, "langfuse_host", None),
            public_key=getattr(settings, "langfuse_public_key", None),
            secret_key=getattr(settings, "langfuse_secret_key", None),
            endpoint_override=getattr(settings, "otel_exporter_otlp_endpoint", None),
            extra_headers=getattr(settings, "otel_exporter_otlp_headers", None),
        )
        if cfg is None:
            return NoopTelemetryContext()
        exporter = OTLPSpanExporter(endpoint=cfg.endpoint, headers=cfg.headers)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        _register_provider(provider)
        return OtelTelemetryContext(
            provider=provider,
            exporter=exporter,
            exporter_kind="langfuse",
            exporter_endpoint=cfg.endpoint,
        )

    return NoopTelemetryContext()


def _register_provider(provider: Any) -> None:
    with _PROVIDER_LOCK:
        _MANAGED_PROVIDERS.append(provider)


def shutdown_telemetry() -> None:
    with _PROVIDER_LOCK:
        providers = list(_MANAGED_PROVIDERS)
        _MANAGED_PROVIDERS.clear()
    for provider in providers:
        try:
            provider.force_flush(2000)
        except Exception:
            pass
        try:
            provider.shutdown()
        except Exception:
            pass
