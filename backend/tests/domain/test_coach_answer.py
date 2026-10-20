"""C0: the answer contract is a closed, per-action rule table.

These tests pin the three things the plan asks for: a bounded brief, a language
that is chosen by controlled metadata rather than inferred from an internal
English prompt, and labels that exist in both languages.
"""
import inspect
import re

import pytest
from pydantic import ValidationError

from backend.domain.coach_answer import (
    ACTION_REGISTRY,
    METRIC_LABELS_BY_LANGUAGE,
    BriefExceedsLimit,
    CoachBrief,
    action_spec,
    limits_for,
    message_catalog,
    project_brief,
    resolve_language,
)
from backend.schemas import CoachAction

CJK = re.compile(r"[\u4e00-\u9fff]")


def test_long_summary_and_extra_findings_are_rejected():
    with pytest.raises(ValidationError):
        CoachBrief(summary="长" * 121, findings=[], next_step="查看记录", evidence_refs=[])
    with pytest.raises(ValidationError):
        CoachBrief(summary="简短结论", findings=["重点"] * 4, next_step="查看记录", evidence_refs=[])


def test_a_single_overlong_finding_is_rejected():
    with pytest.raises(ValidationError):
        CoachBrief(
            summary="简短结论",
            findings=["重点" * 61],
            next_step="查看记录",
            evidence_refs=[],
        )


def test_an_overlong_next_step_is_rejected():
    with pytest.raises(ValidationError):
        CoachBrief(summary="简短结论", findings=[], next_step="下一步" * 41, evidence_refs=[])


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        CoachBrief(
            summary="简短结论",
            findings=[],
            next_step="查看记录",
            evidence_refs=[],
            extra_markdown="## 长篇",
        )


def test_a_brief_may_not_state_its_own_number():
    """Figures are looked up from evidence; text that carries one is not published."""
    with pytest.raises(ValidationError):
        CoachBrief(
            summary="今天摄入 1800 千卡",
            findings=[],
            next_step="查看记录",
            evidence_refs=["energy_intake"],
        )


def test_detailed_mode_only_raises_the_body_limit():
    brief = limits_for("explain_today", "brief")
    detailed = limits_for("explain_today", "detailed")
    assert brief.body_chars == 1200
    assert detailed.body_chars == 3000
    assert brief.summary_chars == detailed.summary_chars == 120
    assert brief.max_findings == detailed.max_findings == 3
    assert brief.finding_chars == detailed.finding_chars == 120


def test_an_unregistered_action_fails_closed():
    assert action_spec("explain_today") is not None
    with pytest.raises(KeyError):
        action_spec("delete_everything")


def test_every_coach_action_is_registered():
    """The registry is the allow-list: an action without a rule has no contract."""
    assert set(ACTION_REGISTRY) == set(CoachAction.__args__)


def test_explicit_request_wins_for_this_turn_only():
    assert resolve_language(requested="en-US", account="zh-CN", default="zh-CN") == "en-US"
    assert resolve_language(requested="zh-CN", account="en-US", default="en-US") == "zh-CN"


def test_account_language_wins_over_the_app_default():
    assert resolve_language(requested=None, account="zh-CN", default="en-US") == "zh-CN"
    assert resolve_language(requested=None, account="en-US", default="zh-CN") == "en-US"


def test_the_default_applies_only_when_nothing_else_is_known():
    assert resolve_language(requested=None, account=None, default="zh-CN") == "zh-CN"


def test_language_resolution_cannot_read_the_prompt_text():
    """An internal English action template must not decide the answer language.

    The function has no text parameter at all, so no caller can hand it the
    generated prompt and have the language inferred from English words.
    """
    parameters = set(inspect.signature(resolve_language).parameters)
    assert parameters == {"requested", "account", "default"}
    for forbidden in ("question", "text", "prompt", "query"):
        assert forbidden not in parameters


def test_message_catalog_is_localized():
    zh = message_catalog("zh-CN")
    en = message_catalog("en-US")
    assert CJK.search(zh.no_evidence)
    assert not CJK.search(en.no_evidence)
    assert zh.no_evidence != en.no_evidence
    assert CJK.search(zh.partial)
    assert not CJK.search(en.partial)
    assert zh.recommendation_prefix != en.recommendation_prefix


def test_metric_labels_exist_in_both_languages():
    zh = METRIC_LABELS_BY_LANGUAGE["zh-CN"]
    en = METRIC_LABELS_BY_LANGUAGE["en-US"]
    assert set(zh) == set(en)
    assert len(zh) >= 9
    for metric, label in en.items():
        assert not CJK.search(label), metric
    for metric, label in zh.items():
        assert CJK.search(label), metric


# --------------------------------------------------------------------------
# the per-action projection
# --------------------------------------------------------------------------

def _brief(**overrides):
    values = {
        "summary": "蛋白质还差一些",
        "findings": ["今天记录完整", "训练量正常"],
        "next_step": "查看今日详情",
        "evidence_refs": ["protein_intake:2026-10-18"],
    }
    values.update(overrides)
    return CoachBrief(**values)


def test_project_brief_renders_the_three_parts_in_order():
    text = project_brief(_brief(), language="zh-CN", action="explain_today")

    assert text.startswith("**蛋白质还差一些**")
    assert "- 今天记录完整" in text
    assert "- 训练量正常" in text
    assert text.rstrip().endswith("查看今日详情")


def test_project_brief_localizes_the_next_step_label():
    zh = project_brief(_brief(), language="zh-CN", action="explain_today")
    en = project_brief(
        _brief(summary="Protein is short", findings=["Records complete"],
               next_step="Open today"),
        language="en-US",
        action="explain_today",
    )

    assert "下一步：" in zh
    assert "Next step: " in en
    assert not CJK.search(en)


def test_project_brief_stays_within_the_action_budget():
    text = project_brief(_brief(), language="zh-CN", action="explain_today")

    assert len(text) <= limits_for("explain_today", "brief").body_chars


def test_project_brief_refuses_instead_of_truncating(monkeypatch):
    """A half sentence published as success is worse than a visible failure."""
    from dataclasses import replace as dc_replace

    from backend.domain import coach_answer as module

    tight = dc_replace(action_spec("explain_today").limits, body_chars=10)
    monkeypatch.setitem(
        module.ACTION_REGISTRY,
        "explain_today",
        dc_replace(action_spec("explain_today"), limits=tight),
    )

    with pytest.raises(BriefExceedsLimit):
        project_brief(_brief(), language="zh-CN", action="explain_today")


def test_project_brief_uses_the_generic_budget_for_an_unregistered_action():
    text = project_brief(_brief(), language="zh-CN", action=None)

    assert len(text) <= limits_for("explain_today", "brief").body_chars
