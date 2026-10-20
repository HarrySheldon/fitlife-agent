from backend.application.ports.coach_answer import CoachTurnRequest
from backend.infrastructure.agent_runtime.coach_answer_adapter import RuntimeCoachAnswerAdapter


def request(action):
    return CoachTurnRequest(
        user_id="synthetic", conversation_id="c1", turn_id="t1",
        question="解释今天 · 2026-10-19", action=action, surface="today",
        date="2026-10-19", language="zh-CN", answer_mode="brief", request_id="t1",
    )


def test_shortcut_display_message_does_not_become_an_untrusted_free_question():
    captured = {}

    def contextual(**kwargs):
        captured.update(kwargs)
        return {"answer_markdown": "ok"}

    RuntimeCoachAnswerAdapter(contextual=contextual).run(request("explain_today"))
    assert captured["question"] is None
    assert captured["date"] == "2026-10-19"
    assert captured["action"] == "explain_today"
    assert captured["language"] == "zh-CN"


def test_free_chat_keeps_the_actual_question():
    captured = []

    def chat(question, user, **kwargs):
        captured.append(question)
        return {"answer_markdown": "ok"}

    RuntimeCoachAnswerAdapter(chat=chat).run(request("chat"))
    assert captured == ["解释今天 · 2026-10-19"]
