from pydantic import BaseModel
import pytest

from backend.agent.runtime import AgentRuntime
from backend.agent.safety import SafetyRefusal
from backend.application.ports.structured_model_gateway import StructuredModelResult


class Suggestion(BaseModel):
    advice: str


class Gateway:
    model = "mock-structured"

    def __init__(self, advice="Try a short walk."):
        self.advice = advice
        self.calls = 0

    def parse_structured(self, **kwargs):
        self.calls += 1
        return StructuredModelResult(Suggestion(advice=self.advice), self.model, {})


def invoke(runtime, gateway, question="Suggest an activity."):
    from backend.agent.structured_workflow import run_structured_agent
    return run_structured_agent(
        operation="smart_entry", question=question, user_id="user-a",
        instructions="Offer safe lifestyle suggestions.", input_text=question,
        response_model=Suggestion, gateway_resolver=lambda: gateway, runtime=runtime,
    )


def test_structured_call_is_persisted_and_model_budget_is_counted():
    runtime = AgentRuntime()
    result = invoke(runtime, Gateway())
    assert result.output.advice == "Try a short walk."
    run = runtime.repository.get(result.run_id, "user-a")
    assert run.status == "succeeded"
    assert run.tool_calls == 1
    assert run.output_tokens > 0
    events = runtime.repository.events(result.run_id, "user-a")
    assert any(event.step == "safety_reviewer" for event in events)
    assert result.request_id == run.request_id


def test_structured_unsafe_output_is_refused_not_coerced_into_valid_schema():
    runtime = AgentRuntime()
    with pytest.raises(SafetyRefusal) as caught:
        invoke(runtime, Gateway("You have diabetes. Take 50 mg daily."))
    assert caught.value.run_id
    assert runtime.repository.get(caught.value.run_id, "user-a").status == "failed"


def test_structured_high_risk_input_never_calls_provider():
    gateway = Gateway()
    with pytest.raises(SafetyRefusal):
        invoke(AgentRuntime(), gateway, question="I have chest pain and cannot breathe.")
    assert gateway.calls == 0


def test_structured_model_transient_retry_is_owned_by_runtime():
    from backend.agent.policy import RuntimePolicy, RetryPolicy
    class TransientGateway(Gateway):
        def parse_structured(self, **kwargs):
            if self.calls == 0:
                self.calls += 1
                raise ConnectionError("private provider response")
            return super().parse_structured(**kwargs)
    gateway = TransientGateway()
    runtime = AgentRuntime(policy=RuntimePolicy(retry=RetryPolicy(base_delay_seconds=0, jitter_ratio=0)))
    result = invoke(runtime, gateway)
    assert gateway.calls == 2
    events = runtime.repository.events(result.run_id, "user-a")
    assert sum(event.event_type == "STEP_RETRY_SCHEDULED" for event in events) == 1
    assert "private provider response" not in repr(events)


def test_structured_deadline_returns_without_waiting_for_provider():
    from threading import Event
    from backend.agent.policy import RuntimePolicy
    from backend.agent.runtime import RunTimedOut
    release = Event()
    class SlowGateway(Gateway):
        def parse_structured(self, **kwargs):
            release.wait(2)
            return super().parse_structured(**kwargs)
    runtime = AgentRuntime(policy=RuntimePolicy(deadline_seconds=0.05))
    try:
        with pytest.raises(RunTimedOut) as caught:
            invoke(runtime, SlowGateway())
        run = runtime.repository.get(caught.value.run_id, "user-a")
        assert run.status == "timed_out"
        assert not release.is_set()
    finally:
        release.set()
