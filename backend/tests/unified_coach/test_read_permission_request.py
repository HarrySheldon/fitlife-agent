import asyncio
import pandas as pd
import pytest
from backend.agent.contracts import AgentCommand
from backend.agent.coach_composition import requested_domains
from backend.agent.context_builder import ExecutionPrincipal
from backend.agent.decision import ToolCall, FinalDecision
from backend.agent.runtime import AgentRuntime
from backend.agent.unified_coach import UnifiedCoachWorkflow
from backend.agent.tools.handlers import BoundFitnessReads
from backend.tests.unified_coach.test_agent_loop import ScriptedDecisionGateway
from backend.tests.unified_coach.test_tool_authorization import executor

QUERY = ToolCall(call_id='read',tool='fitness.query',arguments={'domain':'training','fields':['exercise'],
    'start_date':'2026-11-01','end_date':'2026-11-05'})


def test_unrecognised_expression_can_request_then_receive_explicit_own_record_permission():
    class Records:
        calls=0
        def read_workouts(self,owner):
            assert owner=='owner'
            self.calls+=1
            from backend.tools.workout_analyzer import REQUIRED_WORKOUT_COLUMNS
            return pd.DataFrame(columns=REQUIRED_WORKOUT_COLUMNS)
    records=Records()
    def run(consent, decisions):
        command=AgentCommand('chat','卧推怎么安排','owner',language='zh-CN',read_domains=consent)
        ex=executor(requested_domains(command))
        ex.reads=BoundFitnessReads(records,'owner')
        result=asyncio.run(AgentRuntime().execute(command,UnifiedCoachWorkflow(ScriptedDecisionGateway(decisions),ex)))
        return result,ex
    denied,ex=run((),[QUERY])
    assert '是否允许' in denied.answer_markdown
    assert denied.trace['read_access_request']==['training']
    assert records.calls==0 and ex.executions==0
    assert ex.principal.authorized_domains==frozenset()
    allowed,ex=run(('training',),[QUERY,FinalDecision(body='可以按动作舒适程度逐步安排训练。')])
    assert allowed.answer_markdown
    assert records.calls==1
    assert 'diet' not in ex.principal.authorized_domains


def test_unknown_expression_can_use_public_tools_without_private_permission():
    command=AgentCommand('chat','卧推怎么安排','owner',language='zh-CN',read_domains=())
    ex=executor(requested_domains(command))
    decisions=[ToolCall(call_id='skills',tool='skills.search',arguments={'query':'training'}),
               FinalDecision(body='先按可用器械和动作舒适程度安排训练。')]
    result=asyncio.run(AgentRuntime().execute(command,UnifiedCoachWorkflow(ScriptedDecisionGateway(decisions),ex)))
    assert result.answer_markdown and ex.executions==1


def test_explicit_denial_overrides_selected_read_scope():
    command=AgentCommand('chat','卧推怎么安排，不授权访问训练记录','owner',read_domains=('training',))
    assert 'training' not in requested_domains(command)
    assert 'profile' not in requested_domains(AgentCommand('chat','不授权读取基本档案','owner',read_domains=('profile',)))


def test_no_selection_cannot_read_even_basic_private_goal():
    command=AgentCommand('chat','卧推怎么安排','owner',language='zh-CN',read_domains=())
    ex=executor(requested_domains(command))
    decision=ToolCall(call_id='goal',tool='fitness.query',arguments={'domain':'profile','fields':['goal']})
    result=asyncio.run(AgentRuntime().execute(command,UnifiedCoachWorkflow(ScriptedDecisionGateway([decision]),ex)))
    assert result.trace['read_access_request']==['profile']
    assert ex.executions==0


def test_training_consent_projects_only_training_owned_profile_fields():
    from types import SimpleNamespace
    class Profiles:
        def read_profile(self,owner):
            return SimpleNamespace(model_dump=lambda:{'experience_level':'beginner','goal':'private-goal'})
    command=AgentCommand('chat','卧推怎么安排','owner',language='zh-CN',read_domains=('training',))
    ex=executor(requested_domains(command))
    ex.reads=BoundFitnessReads(Profiles(),'owner')
    decisions=[ToolCall(call_id='experience',tool='fitness.query',arguments={'domain':'profile','fields':['experience_level']}),
               FinalDecision(body='可以从动作舒适的训练开始。')]
    asyncio.run(AgentRuntime().execute(command,UnifiedCoachWorkflow(ScriptedDecisionGateway(decisions),ex)))
    assert ex.observations['experience']['data']=={'experience_level':'beginner'}
    assert 'profile' not in ex.principal.authorized_domains


def test_http_consent_cannot_set_identity_or_unknown_domains():
    from backend.api.coach_conversations import ConversationTurnRequest
    from pydantic import ValidationError
    for extra in ({'read_domains':['other']},{'user_id':'other'},{'action':'explain_today','read_domains':['training']}):
        with pytest.raises(ValidationError):
            ConversationTurnRequest.model_validate({'question':'卧推怎么安排',**extra})
