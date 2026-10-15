import pytest

from backend.safety.business_scope import decide_business_scope


@pytest.mark.parametrize("question", [
    "Did I hit my protein target this week?",
    "How is my protein intake?",
    "What can replace chicken breast for protein?",
    "Create a weekly summary report.",
    "我不想吃鸡胸肉，有什么替代？",
])
def test_supported_health_question_shapes(question):
    assert decide_business_scope(question).scope == "in_scope"


@pytest.mark.parametrize("question", ["Which stocks should I buy?", "What stocks can I sell?"])
def test_explicit_stock_transaction_questions(question):
    assert decide_business_scope(question).scope == "out_of_scope"


def test_repeated_chinese_modifiers_remain_conservative():
    # The child-process watchdog owns adversarial sizes so regressions cannot
    # hang this semantic check in the test runner itself.
    assert decide_business_scope("我的" * 3 + "政治训练").allowed_subtasks == ()
