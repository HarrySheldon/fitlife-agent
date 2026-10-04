import asyncio

import pytest

from backend.agent.telemetry import InMemoryTelemetryContext, SafeTelemetryContext


def test_spans_preserve_parentage_and_redact_unknown_attributes():
    adapter = InMemoryTelemetryContext()
    telemetry = SafeTelemetryContext(adapter)

    async def run():
        async with telemetry.span("fitlife.agent.run", {"policy_version": "v1", "prompt": "private"}):
            async with telemetry.span("fitlife.agent.step", {"input_tokens": 3}):
                pass

    asyncio.run(run())
    outer, inner = adapter.spans
    assert inner.parent_id == outer.span_id
    assert outer.parent_id is None
    assert outer.attributes == {"policy_version": "v1"}
    assert inner.attributes == {"input_tokens": 3}
    assert outer.outcome == inner.outcome == "succeeded"
    assert outer.duration_ms >= 0


@pytest.mark.parametrize("failure_at", ["enter", "exit"])
def test_adapter_failure_neither_changes_success_nor_hides_business_failure(failure_at):
    class BrokenAdapter:
        def span(self, name, attributes):
            class Span:
                async def __aenter__(self):
                    if failure_at == "enter":
                        raise RuntimeError("private adapter details")

                async def __aexit__(self, *args):
                    raise RuntimeError("private adapter details")
            return Span()

    async def run(fail):
        async with SafeTelemetryContext(BrokenAdapter()).span("fitlife.agent.run", {}):
            if fail:
                raise ValueError("business error")
            return "answer"

    assert asyncio.run(run(False)) == "answer"
    with pytest.raises(ValueError, match="business error"):
        asyncio.run(run(True))


def test_business_failure_records_only_low_cardinality_status():
    adapter = InMemoryTelemetryContext()

    async def run():
        async with SafeTelemetryContext(adapter).span("fitlife.agent.run", {}):
            raise ValueError("private health text")

    with pytest.raises(ValueError):
        asyncio.run(run())
    assert adapter.spans[0].outcome == "failed"
    assert "private" not in repr(adapter.spans[0])


def test_concurrent_runs_do_not_share_parents():
    adapter = InMemoryTelemetryContext()
    telemetry = SafeTelemetryContext(adapter)

    async def run():
        async with telemetry.span("fitlife.agent.run", {}):
            await asyncio.sleep(0)
            async with telemetry.span("fitlife.agent.tool", {}):
                pass

    async def both():
        await asyncio.gather(run(), run())

    asyncio.run(both())
    roots = {span.span_id for span in adapter.spans if span.parent_id is None}
    assert len(roots) == 2
    assert {span.parent_id for span in adapter.spans if span.parent_id is not None} == roots


def test_adapter_never_receives_private_cause_and_cannot_suppress_business_error():
    observed = []

    class Adapter:
        def span(self, name, attributes):
            class Span:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, kind, value, traceback):
                    observed.append((str(value), traceback))
                    return True
            return Span()

    async def run():
        async with SafeTelemetryContext(Adapter()).span("fitlife.agent.run", {}):
            raise ValueError("private health data")

    with pytest.raises(ValueError, match="private health data"):
        asyncio.run(run())
    assert observed == [("operation_failed", None)]


def test_final_usage_can_be_recorded_without_sending_private_attributes():
    adapter = InMemoryTelemetryContext()

    async def run():
        async with SafeTelemetryContext(adapter).span("fitlife.agent.run", {}) as span:
            span.set_attributes({"input_tokens": 5, "output_tokens": 2, "prompt": "private"})

    asyncio.run(run())
    assert adapter.spans[0].attributes == {"input_tokens": 5, "output_tokens": 2}


def test_safety_step_records_dedicated_content_free_child_span():
    from backend.agent.runtime import RuntimeContext
    adapter = InMemoryTelemetryContext()
    context = RuntimeContext(telemetry=adapter)
    asyncio.run(context.step("safety_reviewer", lambda: "private draft"))
    review = next(span for span in adapter.spans if span.name == "fitlife.safety.review")
    step = next(span for span in adapter.spans if span.name == "fitlife.agent.step")
    assert review.parent_id == step.span_id
    assert review.outcome == "succeeded"
    assert "private draft" not in repr(adapter.spans)
