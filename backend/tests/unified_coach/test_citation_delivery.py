import asyncio
import pytest
from backend.agent.contracts import AgentCommand
from backend.agent.decision import ToolCall, FinalDecision
from backend.agent.runtime import AgentRuntime, BudgetExceeded
from backend.agent.policy import RuntimePolicy, BudgetPolicy
from backend.agent.unified_coach import UnifiedCoachWorkflow
from backend.tests.unified_coach.test_agent_loop import ScriptedDecisionGateway
from backend.tests.unified_coach.test_tool_authorization import executor


def run(decisions, *, policy=None):
    ex = executor()
    ex.retriever = lambda *args, **kwargs: [{'source': 'fitness_rules.md', 'heading': '恢复',
        'text': '训练后充分恢复。', 'chunk_id': 'chunk-a', 'release_id': 'release-a'}]
    gateway = ScriptedDecisionGateway(decisions)
    result = asyncio.run(AgentRuntime(policy=policy).execute(
        AgentCommand('chat', '今天练胸', 'owner', language='zh-CN'), UnifiedCoachWorkflow(gateway, ex)))
    return result, gateway


def search(call):
    return ToolCall(call_id=call, tool='knowledge.search', arguments={'query': '恢复', 'scope': 'training'})


def test_valid_citation_is_published_without_numeric_false_positive():
    result, _ = run([search('a'), FinalDecision(body='根据资料 E1，训练后应充分恢复。', evidence_refs=['a'])])
    assert 'E1' in result.answer_markdown
    assert result.sources[0]['evidence_id'] == 'E1'


def test_two_searches_have_distinct_ids_and_correct_call_binding():
    result, gateway = run([search('a'), search('b'),
        FinalDecision(body='根据资料 E2，训练后应充分恢复。', evidence_refs=['a']),
        FinalDecision(body='根据资料 E2，训练后应充分恢复。', evidence_refs=['b'])])
    assert len(gateway.requests) == 4
    assert result.sources[0]['evidence_id'] == 'E2'


def test_unknown_citation_is_corrected_in_same_runtime():
    result, gateway = run([search('a'), FinalDecision(body='根据资料 E9，应充分恢复。', evidence_refs=['a']),
        FinalDecision(body='根据资料 E1，应充分恢复。', evidence_refs=['a'])])
    assert 'E9' not in result.answer_markdown
    assert gateway.requests[-1].instructions == gateway.requests[0].instructions
    assert gateway.requests[-1].messages[-1]['source'] == 'citation_error'


def test_evidence_id_confused_with_call_id_gets_one_correction():
    result, gateway = run([search('a'), FinalDecision(body='根据 E1，应充分恢复。', evidence_refs=['E1']),
        FinalDecision(body='根据 E1，应充分恢复。', evidence_refs=['a'])])
    assert len(gateway.requests) == 3
    assert 'E1' in result.answer_markdown


def test_second_invalid_answer_is_never_published():
    from backend.domain.errors import ApplicationError
    with pytest.raises(ApplicationError) as caught:
        run([FinalDecision(body='根据资料 E9，应充分恢复。')]*2)
    assert caught.value.code == 'KNOWLEDGE_CITATION_INVALID'
    assert 'E9' not in caught.value.message


def test_citation_repair_cannot_reset_model_budget():
    with pytest.raises(BudgetExceeded):
        run([FinalDecision(body='根据资料 E9，应充分恢复。')],
            policy=RuntimePolicy(budget=BudgetPolicy(max_model_calls=1)))


def test_valid_citation_does_not_authorize_numeric_prose():
    with pytest.raises(ValueError, match='UNVERIFIED_NUMERIC_PROSE'):
        run([search('a'), FinalDecision(body='根据 E1，每天练100组。', evidence_refs=['a'])])
