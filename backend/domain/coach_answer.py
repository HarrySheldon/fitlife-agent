"""The controlled answer contract for Coach actions.

Three things live here and nowhere else.

**Language.** It is resolved from controlled metadata: an explicit request for this
turn, then the account setting, then the app default. `resolve_language` has no text
parameter, so no caller can hand it the generated prompt and have the answer language
inferred from English words. That matters because this codebase builds every internal
action prompt in English; the prompt says nothing about who is reading the answer.

**Shape.** A brief is a summary, a few findings, one next step, and references to
evidence ids. It is not open Markdown. A figure is looked up by the renderer from the
catalog, so text that carries a number is refused rather than published unverified.

**Limits.** One registry keyed by action. Adding an action means adding a rule here;
an action with no rule cannot be rendered at all. That is deliberate: a missing entry
must fail closed instead of silently inheriting someone else's budget.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

AnswerLanguage = Literal["zh-CN", "en-US"]
AnswerMode = Literal["brief", "detailed"]

LANGUAGES: tuple[AnswerLanguage, ...] = ("zh-CN", "en-US")

# Matches the account preference default, so an unconfigured account and an
# unconfigured app agree instead of drifting apart.
DEFAULT_LANGUAGE: AnswerLanguage = "en-US"

# Arabic digits, percentages, and units that imply a quantity. The check is blunt on
# purpose: it can tell that a number is present and cannot tell whether it is right,
# so it refuses rather than guesses.
_NUMBER = re.compile(r"[0-9%％]|千卡|大卡|卡路里|kcal|calorie", re.IGNORECASE)


@dataclass(frozen=True)
class AnswerLimits:
    summary_chars: int = 120
    max_findings: int = 3
    finding_chars: int = 120
    next_step_chars: int = 120
    body_chars: int = 1200
    detailed_body_chars: int = 3000


@dataclass(frozen=True)
class MessageCatalog:
    no_evidence: str
    partial: str
    recommendation_prefix: str
    # The label carries its own separator so the Chinese colon is not replaced by an
    # ASCII one, or the reverse.
    next_step_label: str
    # The product-boundary responses. These used to be Chinese literals in the
    # boundary workflow, so an English account was refused in Chinese.
    greeting: str
    clarification: str
    out_of_scope: str


_CATALOGS: Mapping[AnswerLanguage, MessageCatalog] = {
    "zh-CN": MessageCatalog(
        no_evidence="当前没有足够的记录，无法核实这些数值。",
        partial="部分数值内容无法核实，已省略。",
        recommendation_prefix="建议：",
        next_step_label="下一步：",
        greeting="你好！我可以帮助你了解 FitLife，以及健身、训练和饮食问题。",
        clarification="请单独说明你希望获得的健身、训练或饮食帮助。",
        out_of_scope="我可以帮助你处理健身、训练、饮食和 FitLife 使用问题，无法提供选股或其他无关服务。",
    ),
    "en-US": MessageCatalog(
        no_evidence="There are not enough records to verify these figures.",
        partial="Some figures could not be verified and were left out.",
        recommendation_prefix="Suggestion: ",
        next_step_label="Next step: ",
        greeting="Hello! I can help with FitLife, training, and nutrition questions.",
        clarification="Please describe the fitness, training, or nutrition help you want, on its own.",
        out_of_scope="I can help with fitness, training, nutrition, and using FitLife. I cannot help with stock picking or other unrelated requests.",
    ),
}

# A metric without a label in the chosen language is not rendered. Falling back to the
# metric identifier would put an internal name in front of a user.
METRIC_LABELS_BY_LANGUAGE: Mapping[AnswerLanguage, Mapping[str, str]] = {
    "zh-CN": {
        "energy_intake": "热量摄入",
        "protein_intake": "蛋白质摄入",
        "carbohydrate_intake": "碳水摄入",
        "fat_intake": "脂肪摄入",
        "recorded_day_mean_energy": "有记录日期的每日平均热量",
        "recorded_day_mean_protein": "有记录日期的每日平均蛋白质",
        "training_record_count": "训练记录条数",
        "training_duration": "训练时长",
        "strength_volume": "力量训练容量",
    },
    "en-US": {
        "energy_intake": "Calorie intake",
        "protein_intake": "Protein intake",
        "carbohydrate_intake": "Carbohydrate intake",
        "fat_intake": "Fat intake",
        "recorded_day_mean_energy": "Mean daily calories on recorded days",
        "recorded_day_mean_protein": "Mean daily protein on recorded days",
        "training_record_count": "Training record count",
        "training_duration": "Training duration",
        "strength_volume": "Strength training volume",
    },
}


def message_catalog(language: AnswerLanguage) -> MessageCatalog:
    return _CATALOGS[language]


def metric_label(language: AnswerLanguage, metric: str) -> str | None:
    return METRIC_LABELS_BY_LANGUAGE[language].get(metric)


def resolve_language(
    *,
    requested: str | None = None,
    account: str | None = None,
    default: str | None = DEFAULT_LANGUAGE,
) -> AnswerLanguage:
    """Explicit request for this turn, then the account, then the app default."""
    for candidate in (requested, account, default):
        if candidate in LANGUAGES:
            return candidate  # type: ignore[return-value]
    return DEFAULT_LANGUAGE


class CoachBrief(BaseModel):
    """The only shape a quick action may publish."""

    model_config = ConfigDict(extra="forbid", strict=True)

    summary: str = Field(min_length=1, max_length=120)
    findings: list[str] = Field(default_factory=list, max_length=3)
    next_step: str = Field(min_length=1, max_length=120)
    evidence_refs: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("summary", "next_step")
    @classmethod
    def text_carries_no_figure(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A brief field must not be blank")
        if _NUMBER.search(value):
            raise ValueError("A brief may reference evidence, not state a figure")
        return value

    @field_validator("findings")
    @classmethod
    def each_finding_is_bounded(cls, value: list[str]) -> list[str]:
        for item in value:
            if not item.strip():
                raise ValueError("A finding must not be blank")
            if len(item) > 120:
                raise ValueError("A finding must not exceed 120 characters")
            if _NUMBER.search(item):
                raise ValueError("A finding may reference evidence, not state a figure")
        return value


@dataclass(frozen=True)
class ActionSpec:
    action: str
    default_mode: AnswerMode
    supports_evidence: bool
    limits: AnswerLimits = AnswerLimits()


# Keyed by the CoachAction literal. `test_every_coach_action_is_registered` keeps the
# two lists equal, so an action cannot be exposed to clients without a contract.
ACTION_REGISTRY: Mapping[str, ActionSpec] = {
    "explain_today": ActionSpec("explain_today", "brief", True),
    "suggest_next_meal": ActionSpec("suggest_next_meal", "brief", True),
    "adjust_today_training": ActionSpec("adjust_today_training", "brief", True),
    "explain_weekly_report": ActionSpec("explain_weekly_report", "brief", True),
    "adjust_next_plan": ActionSpec("adjust_next_plan", "brief", True),
    "suggest_targets": ActionSpec("suggest_targets", "brief", True),
}

# Internal result contracts, not additional public quick-action buttons.
ADVICE_REGISTRY: Mapping[str, ActionSpec] = {
    'training_plan_advice': ActionSpec('training_plan_advice', 'detailed', True,
        AnswerLimits(body_chars=3000, detailed_body_chars=6000)),
}


def action_spec(action: str) -> ActionSpec:
    try:
        return ACTION_REGISTRY[action]
    except KeyError:
        raise KeyError(f"No answer contract is registered for action {action!r}") from None


def limits_for(action: str, mode: AnswerMode = "brief") -> AnswerLimits:
    """The limits that apply to this action in this mode.

    Detailed mode raises the body allowance only. Summary, findings and next step stay
    bounded, because "explain in more detail" is about the prose, not permission to
    dump an unbounded card.
    """
    limits = action_spec(action).limits
    if mode == "detailed":
        return replace(limits, body_chars=limits.detailed_body_chars)
    return limits


def limits_for_or_default(action: str | None, mode: AnswerMode = "brief") -> AnswerLimits:
    """Limits for a run that is not a registered quick action (chat, evaluation).

    An unknown action does not inherit a quick action's rule; it gets the generic
    budget. The registry still fails closed for `action_spec`, which is what the
    action endpoint calls.
    """
    spec = (ACTION_REGISTRY.get(action) or ADVICE_REGISTRY.get(action)) if action else None
    limits = spec.limits if spec is not None else AnswerLimits()
    if mode == "detailed":
        return replace(limits, body_chars=limits.detailed_body_chars)
    return limits


def output_token_limit(limits: AnswerLimits) -> int:
    """A token ceiling that comfortably covers the character budget.

    One character is roughly one token for Chinese and well under one for English, so
    a 1.5x factor plus a fixed margin keeps a correct answer from being cut off while
    still bounding the generation. It is a ceiling, not a target.
    """
    return int(limits.body_chars * 1.5) + 256


class BriefExceedsLimit(ValueError):
    """The projection would not fit the action's budget.

    Raised rather than truncated: a half sentence published as a success is worse than
    a visible failure, and the caller still has the retry budget to fix it.
    """


def project_brief(
    brief: CoachBrief,
    *,
    language: AnswerLanguage,
    action: str | None,
    mode: AnswerMode = "brief",
) -> str:
    """Render a brief for publication, bounded by the action's limits.

    Findings are already capped at three by the model. The limit is re-checked here so
    a future action with a smaller allowance cannot publish a longer card by accident.
    """
    catalog = message_catalog(language)
    limits = limits_for_or_default(action, mode)
    if len(brief.findings) > limits.max_findings:
        raise BriefExceedsLimit(
            f"{len(brief.findings)} findings exceed the {limits.max_findings} allowed"
        )

    lines = [f"**{brief.summary}**"]
    lines.extend(f"- {item}" for item in brief.findings)
    lines.append(f"{catalog.next_step_label}{brief.next_step}")
    text = "\n".join(lines)

    if len(text) > limits.body_chars:
        raise BriefExceedsLimit(
            f"{len(text)} characters exceed the {limits.body_chars} allowed"
        )
    return text
