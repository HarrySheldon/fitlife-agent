import pytest
from pydantic import TypeAdapter
from backend.agent.decision import AgentDecision


def test_final_cannot_smuggle_tool_call():
    with pytest.raises(ValueError):
        TypeAdapter(AgentDecision).validate_python({
            'kind': 'final', 'body': '建议', 'tool': 'delete_account'})


def test_blank_final_is_rejected():
    with pytest.raises(ValueError):
        TypeAdapter(AgentDecision).validate_python({'kind': 'final', 'body': '   '})


def test_adapter_uses_structured_generation_not_native_probe():
    from backend.infrastructure.model_gateway.agent_decision_adapter import StructuredDecisionAdapter
    from backend.application.ports.agent_decision_gateway import AgentDecisionRequest
    from backend.application.ports.structured_model_gateway import StructuredModelResult

    class Gateway:
        model = 'fake'

        def parse_structured(self, **kwargs):
            output = kwargs['response_model'].model_validate({'decision': {'kind': 'ask', 'question': '器械有哪些？'}})
            return StructuredModelResult(output, self.model, {'total_tokens': 12})

    result = StructuredDecisionAdapter(Gateway()).decide(AgentDecisionRequest('rules', (), ()))
    assert result.decision.question == '器械有哪些？'
    assert result.usage == {'total_tokens': 12}


def test_dynamic_tool_arguments_use_local_json_mode_without_mutating_connection():
    from backend.infrastructure.model_gateway.agent_decision_adapter import StructuredDecisionAdapter
    from backend.application.ports.agent_decision_gateway import AgentDecisionRequest
    from backend.application.ports.structured_model_gateway import StructuredModelResult

    class Gateway:
        model = 'fake'
        structured_mode = 'native'

        def parse_structured(self, **kwargs):
            assert self.structured_mode == 'json'
            return StructuredModelResult(kwargs['response_model'].model_validate({'decision': {
                'kind': 'ask', 'question': '有什么器械？'}}), self.model, {})

    gateway = Gateway()
    StructuredDecisionAdapter(gateway).decide(AgentDecisionRequest('rules', (), ()))
    assert gateway.structured_mode == 'native'


@pytest.mark.parametrize('protocol', ['responses', 'chat_completions'])
def test_real_provider_adapter_parses_action_json_with_fake_client(protocol):
    from types import SimpleNamespace
    from backend.infrastructure.model_gateway.agent_decision_adapter import StructuredDecisionAdapter
    from backend.infrastructure.model_gateway.openai_responses import OpenAIResponsesAdapter
    from backend.infrastructure.model_gateway.openai_chat_completions import OpenAIChatCompletionsAdapter
    from backend.application.ports.agent_decision_gateway import AgentDecisionRequest
    raw = '{"decision":{"kind":"call","call_id":"a","tool":"skills.search","arguments":{"query":"training"}}}'
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        assert 'tools' not in kwargs
        return SimpleNamespace(output_text=raw, model='resolved', usage=None,
            choices=[SimpleNamespace(message=SimpleNamespace(content=raw))])
    client = SimpleNamespace(responses=SimpleNamespace(create=create),
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    adapter = (OpenAIResponsesAdapter(client=client, model='fake') if protocol == 'responses'
               else OpenAIChatCompletionsAdapter(client=client, model='fake'))
    result = StructuredDecisionAdapter(adapter).decide(AgentDecisionRequest('rules', (), (), 512))
    assert result.decision.arguments == {'query': 'training'}
    assert result.model == 'resolved'
    assert len(calls) == 1
    assert 512 in calls[0].values()
