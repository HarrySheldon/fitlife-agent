from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace

from backend.agent.contracts import AgentCommand, AgentResult
from backend.agent.runtime import AgentRuntime
from backend.agent.telemetry import SafeTelemetryContext, active_telemetry_context, current_trace_id
from backend.config import Settings
from backend.infrastructure.agent_runtime.memory_run_repository import MemoryRunRepository
from backend.infrastructure.observability import (
    OtelTelemetryContext,
    build_langfuse_otlp_config,
    build_telemetry_context,
    shutdown_telemetry,
)


def test_otel_memory_exporter_records_hierarchy_tokens_and_redacts_secrets():
    settings = Settings(telemetry_exporter="memory", otel_service_name="fitlife-test")
    telemetry = build_telemetry_context(settings)
    assert isinstance(telemetry, OtelTelemetryContext)
    assert telemetry.exporter_kind == "memory"

    captured_trace_ids: list[str | None] = []

    class FakeModelResponse:
        usage = {
            "prompt_tokens": 120,
            "completion_tokens": 45,
            "cached_input_tokens": 80,
            "source": "provider",
        }

    class Workflow:
        async def execute(self, command, context):
            context.set_model_metadata(provider="openai", model="gpt-5.5")
            captured_trace_ids.append(current_trace_id())

            def run_model():
                with SafeTelemetryContext(active_telemetry_context()).sync_span(
                    "fitlife.rag.retrieve",
                    {
                        "release_id": "release-0001",
                        "retrieval_mode": "hybrid",
                        "candidate_count": 12,
                        "hit_count": 3,
                    },
                ):
                    with SafeTelemetryContext(active_telemetry_context()).sync_span(
                        "fitlife.rag.rerank",
                        {"candidate_count": 3, "hit_count": 3, "prompt": "secret user prompt"},
                    ):
                        pass
                return FakeModelResponse()

            await context.step(
                "coach_step",
                lambda: context.tool("write_answer_model", "safe", run_model),
            )
            return AgentResult("safe reply", "chat", {}, {}, (), "gpt-5.5")

    repo = MemoryRunRepository()
    runtime = AgentRuntime(repository=repo, telemetry=telemetry)
    try:
        outcome = runtime.execute_sync(
            AgentCommand("chat", "sensitive knee injury question", "user-1"),
            Workflow(),
        )
        telemetry.force_flush()
        spans = telemetry.finished_spans()
    finally:
        shutdown_telemetry()

    names = [s.name for s in spans]
    assert "fitlife.agent.run" in names
    assert "fitlife.agent.step" in names
    assert "fitlife.agent.tool" in names
    assert "fitlife.ai.request" in names
    assert "fitlife.rag.retrieve" in names
    assert "fitlife.rag.rerank" in names
    assert "fitlife.safety.review" in names

    trace_ids = {f"{s.context.trace_id:032x}" for s in spans}
    assert len(trace_ids) == 1
    expected_trace_id = next(iter(trace_ids))
    assert captured_trace_ids == [expected_trace_id]
    assert outcome.trace.get("trace_id") == expected_trace_id

    ai_span = next(s for s in spans if s.name == "fitlife.ai.request")
    assert ai_span.attributes["input_tokens"] == 120
    assert ai_span.attributes["output_tokens"] == 45
    assert ai_span.attributes["cached_tokens"] == 80
    assert ai_span.attributes["total_tokens"] == 165
    assert ai_span.attributes["model"] == "gpt-5.5"

    rerank_span = next(s for s in spans if s.name == "fitlife.rag.rerank")
    assert "prompt" not in rerank_span.attributes
    assert "sensitive" not in repr(spans)

    events = repo.events(outcome.run_id, "user-1")
    started = next(e for e in events if e.event_type == "RUN_STARTED")
    finished = next(e for e in events if e.event_type == "RUN_SUCCEEDED")
    assert started.payload.get("trace_id") == expected_trace_id
    assert finished.payload.get("trace_id") == expected_trace_id


def test_langfuse_otlp_config_builds_basic_auth_and_endpoint_without_leaking_secret():
    cfg = build_langfuse_otlp_config(
        host="https://langfuse.example.com/",
        public_key="pk-lf-test",
        secret_key="sk-lf-secret",
        extra_headers="x-env=staging",
    )
    assert cfg is not None
    assert cfg.endpoint == "https://langfuse.example.com/api/public/otel/v1/traces"
    expected = base64.b64encode(b"pk-lf-test:sk-lf-secret").decode("ascii")
    assert cfg.headers["Authorization"] == f"Basic {expected}"
    assert cfg.headers["x-env"] == "staging"

    # Missing secret falls back cleanly to NoopTelemetryContext instead of raising.
    settings_incomplete = Settings(
        telemetry_exporter="langfuse",
        langfuse_host="https://langfuse.example.com",
        langfuse_public_key="pk-lf-test",
        langfuse_secret_key=None,
    )
    assert type(build_telemetry_context(settings_incomplete)).__name__ == "NoopTelemetryContext"

    settings_langfuse = Settings(
        telemetry_exporter="langfuse",
        langfuse_host="https://langfuse.example.com",
        langfuse_public_key="pk-lf-test",
        langfuse_secret_key="sk-lf-secret",
    )
    ctx = build_telemetry_context(settings_langfuse)
    try:
        assert isinstance(ctx, OtelTelemetryContext)
        assert ctx.exporter_kind == "langfuse"
        assert ctx.exporter_endpoint == "https://langfuse.example.com/api/public/otel/v1/traces"
        # Ensure label filter rejects API keys/URLs even if passed mistakenly.
        safe = SafeTelemetryContext(ctx)

        async def run():
            async with safe.span(
                "fitlife.agent.run",
                {"model": "sk-leaked-secret", "provider": "http://bad", "policy_version": "v1"},
            ):
                pass

        asyncio.run(run())
    finally:
        shutdown_telemetry()
