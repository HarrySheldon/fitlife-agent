import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from backend.agent import graph, structured_workflow
from backend.agent.grounded_answer import GroundedAnswer
from backend.agent.runtime import AgentRuntime
from backend.application.ports.structured_model_gateway import StructuredModelResult
from backend.safety.gate import SafetyRefusal
from backend.safety.review import ReviewVerdict
from backend.tests.test_safety_review_entry import _FreeFormGateway, FileFitnessRepository, DEFAULT_PROFILE


class Candidate(BaseModel):
    text: str


class Gateway(_FreeFormGateway):
    def __init__(self, refuse=False):
        self.calls = []
        self.refuse = refuse

    def write_answer(self, state):
        return "糖尿病患者需要关注饮食。"

    def parse_structured(self, *, instructions, input_text, response_model):
        self.calls.append((response_model, json.loads(input_text) if input_text.startswith('{') else input_text))
        if response_model is ReviewVerdict:
            output = ReviewVerdict(outcome="refuse" if self.refuse else "allow",
                                   risk_category="harassment" if self.refuse else "low")
        elif response_model is GroundedAnswer:
            output = GroundedAnswer(blocks=[])
        else:
            output = Candidate(text="建议保持规律饮食。")
        return StructuredModelResult(output, self.model, {})


def chat(monkeypatch, mode, grounding="legacy"):
    gateway = Gateway()
    repository = FileFitnessRepository()
    repository.read_profile = lambda user_id=None: DEFAULT_PROFILE
    monkeypatch.setattr(graph, "DEFAULT_AGENT_RUNTIME", AgentRuntime())
    monkeypatch.setattr(graph, "_review_mode", lambda: mode)
    monkeypatch.setattr(graph, "_grounding_mode", lambda: grounding)
    result = graph.run_fitlife_agent("我想了解一般饮食", "u1", repository=repository, gateway=gateway)
    return result, gateway


@pytest.mark.parametrize("mode", ["shadow", "enforce"])
def test_public_chat_reuses_gateway_and_preserves_single_notice(monkeypatch, mode):
    baseline, _ = chat(monkeypatch, "off")
    result, gateway = chat(monkeypatch, mode)
    assert [model for model, _ in gateway.calls] == [ReviewVerdict]
    assert result["answer_markdown"] == baseline["answer_markdown"]


def test_public_chat_evidence_uses_resolved_gateway(monkeypatch):
    _, gateway = chat(monkeypatch, "enforce", "evidence")
    assert [model for model, _ in gateway.calls] == [GroundedAnswer, ReviewVerdict]


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
def test_structured_public_entry_honours_mode(monkeypatch, mode):
    gateway = Gateway(refuse=True)
    monkeypatch.setattr(structured_workflow, "get_settings", lambda: SimpleNamespace(safety_review_mode=mode), raising=False)
    def run():
        return structured_workflow.run_structured_agent(
            operation="smart_entry", question="记录饮食", user_id="u1",
            instructions="Return a candidate", input_text="鸡胸肉", response_model=Candidate,
            gateway_resolver=lambda: gateway, runtime=AgentRuntime(),
        )
    if mode == "enforce":
        with pytest.raises(SafetyRefusal):
            run()
    else:
        assert run().output.text == "建议保持规律饮食。"
    assert [model for model, _ in gateway.calls] == ([Candidate] if mode == "off" else [Candidate, ReviewVerdict])


@pytest.mark.parametrize("mode", ["shadow", "enforce"])
def test_structured_review_provider_failure_preserves_typed_candidate(monkeypatch, mode):
    class UnavailableGateway(Gateway):
        def parse_structured(self, **kwargs):
            if kwargs["response_model"] is ReviewVerdict:
                raise ValueError("private provider detail")
            return super().parse_structured(**kwargs)

    monkeypatch.setattr(structured_workflow, "get_settings", lambda: SimpleNamespace(safety_review_mode=mode))
    result = structured_workflow.run_structured_agent(
        operation="smart_entry", question="记录饮食", user_id="u1",
        instructions="Return a candidate", input_text="鸡胸肉", response_model=Candidate,
        gateway_resolver=UnavailableGateway, runtime=AgentRuntime(),
    )
    assert result.output == Candidate(text="建议保持规律饮食。")
    assert "private" not in result.output.model_dump_json()
