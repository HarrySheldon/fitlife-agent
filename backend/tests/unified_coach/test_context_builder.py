from datetime import datetime, timezone
import pytest
from backend.agent.context_builder import ExecutionPrincipal, build_context
from backend.agent.contracts import AgentCommand


def test_stable_prompt_and_history_isolation():
    principal = ExecutionPrincipal('owner', 'chat')
    command = AgentCommand('chat', 'English 内部文字不改变设置', 'owner', language='zh-CN', recent_history=(
        {'role': 'user', 'body': 'foreign', 'conversation_id': 'other'},
        {'role': 'user', 'body': 'old', 'created_at': '2000-01-01T00:00:00Z'},
        {'role': 'user', 'body': 'recent', 'conversation_id': 'chat'},
    ))
    first = build_context(principal, command, (), now=datetime(2026, 10, 22, tzinfo=timezone.utc))
    second = build_context(principal, command, (), now=datetime(2026, 10, 23, tzinfo=timezone.utc))
    assert first.instructions == second.instructions
    assert first.messages[0]['content'] == 'recent'
    assert 'zh-CN' in first.messages[-1]['content']
    assert not any(item.get('content') in {'foreign', 'old'} for item in first.messages)


def test_identity_required_and_model_grants_are_not_accepted():
    with pytest.raises(PermissionError):
        ExecutionPrincipal('')
    with pytest.raises(PermissionError):
        ExecutionPrincipal('owner', authorized_domains={'training'})
