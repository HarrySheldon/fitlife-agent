import pytest

from backend.safety.business_scope import decide_business_scope


@pytest.mark.parametrize('text', [
    '教练你好，我需要今天练胸，给出一份完整的训练计划',
    '给出一份完整的训练计划',
    '教练你好，安排训练计划',
    'Hi coach, I want a complete chest workout today',
])
def test_normal_request_is_not_rejected_by_expression(text):
    decision = decide_business_scope(text, planner_consulted=True)
    assert decision.scope != 'out_of_scope'
    assert not decision.needs_clarification
