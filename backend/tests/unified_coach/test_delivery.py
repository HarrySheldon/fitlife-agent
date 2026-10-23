import pytest
from backend.agent.coach_delivery import project_answer
from backend.agent.decision import AskDecision, FinalDecision
from backend.agent.contracts import AgentCommand
from backend.tests.unified_coach.test_tool_authorization import executor


@pytest.mark.parametrize('text,code', [
    ('已激活你的训练计划', 'UNCONFIRMED_WRITE_CLAIM'),
    ('联系 user@example.com', 'PRIVATE_DATA_IN_OUTPUT'),
    ('![tracking](https://evil.example)', 'UNSAFE_OUTPUT_MARKUP'),
    ('你昨天做了100kg', 'UNVERIFIED_NUMERIC_PROSE'),
])
def test_unsafe_draft_never_becomes_publishable(text, code):
    with pytest.raises(ValueError, match=code):
        project_answer(FinalDecision(body=text), executor(), AgentCommand('chat', '训练', 'owner'))


def test_account_revocation_is_checked_even_for_question_without_evidence():
    ex = executor(authorize=lambda p: (_ for _ in ()).throw(PermissionError('REVOKED')))
    with pytest.raises(PermissionError, match='REVOKED'):
        project_answer(AskDecision(question='你有什么器械？'), ex, AgentCommand('chat', '训练', 'owner'))


@pytest.mark.parametrize('decision', [
    AskDecision(question='你昨天做了100kg，今天继续吗？'),
    FinalDecision(body='Yesterday you lifted one hundred kilograms.'),
    AskDecision(question='Yesterday you lifted one hundred kilograms, right?'),
])
def test_questions_and_spelled_quantities_cannot_bypass_evidence(decision):
    with pytest.raises(ValueError, match='UNVERIFIED_NUMERIC_PROSE'):
        project_answer(decision, executor(), AgentCommand('chat', '训练', 'owner'))


def test_required_review_failure_withholds_even_a_low_risk_original_draft():
    import asyncio
    from backend.agent.coach_delivery import review_delivery
    from backend.agent.runtime import RuntimeContext
    class BrokenReview:
        model = 'offline'
        def parse_structured(self, **kwargs):
            raise OSError('synthetic unavailable')
    text, verdict = asyncio.run(review_delivery(FinalDecision(body='PRIVATE_SYNTHETIC_DRAFT'), executor(),
        AgentCommand('chat', '今天训练', 'owner', language='zh-CN'), RuntimeContext(), gateway=BrokenReview(), mode='enforce'))
    assert 'PRIVATE_SYNTHETIC_DRAFT' not in text
    assert verdict.risk_category == 'review_unavailable'
