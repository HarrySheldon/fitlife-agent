import asyncio
import pytest
from backend.agent.contracts import AgentCommand
from backend.agent.decision import AskDecision, ToolCall, FinalDecision
from backend.agent.runtime import AgentRuntime, BudgetExceeded
from backend.agent.unified_coach import UnifiedCoachWorkflow
from backend.application.ports.agent_decision_gateway import AgentDecisionResult
from backend.tests.unified_coach.test_tool_authorization import executor


class ScriptedDecisionGateway:
    model = 'offline'

    def __init__(self, decisions):
        self.decisions = iter(decisions)
        self.requests = []

    def decide(self, request):
        self.requests.append(request)
        return AgentDecisionResult(next(self.decisions), self.model, {'total_tokens': 10})


def execute(decisions, **kwargs):
    ex = executor()
    gateway = ScriptedDecisionGateway(decisions)
    command = AgentCommand('chat', '教练你好，我需要今天练胸，给出一份完整的训练计划', 'owner', language='zh-CN')
    result = asyncio.run(AgentRuntime().execute(command, UnifiedCoachWorkflow(gateway, ex, **kwargs)))
    return result, gateway


def test_skill_discovery_then_specific_question_is_published():
    result, gateway = execute([
        ToolCall(call_id='a', tool='skills.search', arguments={'query': '练胸'}),
        ToolCall(call_id='b', tool='resources.read', arguments={'resource_id': 'skill:training-plan'}),
        AskDecision(question='你可用的器械有哪些？是否有相关身体限制？'),
    ])
    assert '器械' in result.answer_markdown
    assert result.trace['decision_count'] == 3
    assert result.tool_results == {}
    assert all(request.instructions == gateway.requests[0].instructions for request in gateway.requests)
    assert gateway.requests[1].messages[:len(gateway.requests[0].messages)] == gateway.requests[0].messages


def test_two_denied_actions_end_run_without_fallback():
    with pytest.raises(ValueError, match='AGENT_ACTION_FAILED'):
        execute([ToolCall(call_id=str(i), tool='delete_account', arguments={}) for i in range(2)])


def test_numeric_fact_without_evidence_is_not_published():
    with pytest.raises(ValueError, match='UNVERIFIED_NUMERIC_PROSE'):
        execute([FinalDecision(body='你昨天训练了100kg。')])


def test_validated_suggestion_is_rendered_from_evidence():
    result, _ = execute([
        ToolCall(call_id='plan', tool='fitness.calculate', arguments={'operation': 'validate_training',
            'exercises': [{'name': '俯卧撑', 'sets': 3, 'reps': 10, 'rest_seconds': 60}]}),
        FinalDecision(body='请在动作舒适的前提下训练；不适时停止。', evidence_refs=['plan']),
    ])
    assert '3 组 × 10 次' in result.answer_markdown
    assert result.tool_results == {}


def test_enforce_without_reviewer_does_not_publish_draft():
    with pytest.raises(Exception, match='reviewer unavailable'):
        execute([FinalDecision(body='安全的建议。')], review_mode='enforce')


def test_model_call_budget_cannot_be_reset_by_loop():
    from backend.agent.policy import RuntimePolicy, BudgetPolicy
    gateway = ScriptedDecisionGateway([
        ToolCall(call_id='a', tool='skills.search', arguments={'query': '训练'}),
        AskDecision(question='你有什么器械？')])
    command = AgentCommand('chat', '今天训练', 'owner', language='zh-CN')
    with pytest.raises(BudgetExceeded):
        asyncio.run(AgentRuntime(policy=RuntimePolicy(budget=BudgetPolicy(max_model_calls=1))).execute(
            command, UnifiedCoachWorkflow(gateway, executor())))
    assert len(gateway.requests) == 1


def test_tool_budget_reservation_happens_before_handler():
    from backend.agent.policy import RuntimePolicy, BudgetPolicy
    gateway = ScriptedDecisionGateway([ToolCall(call_id='a', tool='skills.search', arguments={'query': '训练'})])
    ex = executor()
    with pytest.raises(BudgetExceeded):
        asyncio.run(AgentRuntime(policy=RuntimePolicy(budget=BudgetPolicy(max_tool_calls=1))).execute(
            AgentCommand('chat', '今天训练', 'owner'), UnifiedCoachWorkflow(gateway, ex)))
    assert ex.executions == 0


def test_skill_change_during_model_call_prevents_final_publication(tmp_path):
    import shutil
    from pathlib import Path
    from backend.agent.skills.catalog import SkillCatalog, SkillResourceError
    source = Path(__file__).resolve().parents[2] / 'coach_skills'
    shutil.copytree(source, tmp_path / 'skills')
    ex = executor()
    ex.catalog = SkillCatalog(tmp_path / 'skills')
    class Gateway:
        model = 'offline'
        def decide(self, request):
            (tmp_path / 'skills' / 'training-plan' / 'SKILL.md').write_text('changed', encoding='utf-8')
            return AgentDecisionResult(FinalDecision(body='原草稿不能发布'), self.model, {})
    with pytest.raises(SkillResourceError, match='RESOURCE_VERSION_CHANGED'):
        asyncio.run(AgentRuntime().execute(AgentCommand('chat', '今天训练', 'owner'), UnifiedCoachWorkflow(Gateway(), ex)))


def test_new_skill_and_reference_use_the_same_executor_and_runtime(tmp_path):
    import json
    from backend.agent.skills.catalog import SkillCatalog
    folder = tmp_path / 'recovery'
    (folder / 'references').mkdir(parents=True)
    (folder / 'skill.json').write_text(json.dumps({'id': 'recovery', 'version': '1',
        'title': 'Recovery', 'description': 'Rest and recovery'}), encoding='utf-8')
    (folder / 'SKILL.md').write_text('Read the sleep reference only when needed.', encoding='utf-8')
    (folder / 'references' / 'sleep.md').write_text('Keep a regular sleep routine.', encoding='utf-8')
    ex = executor()
    ex.catalog = SkillCatalog(tmp_path)
    gateway = ScriptedDecisionGateway([
        ToolCall(call_id='a', tool='skills.search', arguments={'query': 'Recovery'}),
        ToolCall(call_id='b', tool='resources.read', arguments={'resource_id': 'skill:recovery'}),
        ToolCall(call_id='c', tool='resources.read', arguments={'resource_id': 'skill:recovery/reference:sleep'}),
        FinalDecision(body='保持规律休息，逐步恢复训练。'),
    ])
    outcome = asyncio.run(AgentRuntime().execute(AgentCommand('chat', '今天训练', 'owner'), UnifiedCoachWorkflow(gateway, ex)))
    assert outcome.trace['loaded_skill_ids'] == ['skill:recovery', 'skill:recovery/reference:sleep']
    assert outcome.trace['decision_count'] == 4
