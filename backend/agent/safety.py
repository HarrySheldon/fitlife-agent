"""Mandatory, conservative FitLife safety rules and reviewed-result projection.

Rules are a deterministic baseline, not a medical classifier or a diagnostic
service. Additional reviewers can tighten decisions but cannot relax the rules.
"""
from __future__ import annotations

import re
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from backend.domain.errors import ApplicationError

SAFETY_RULE_VERSION = "fitlife-safety-v1"
MAX_QUESTION_CHARS = 8_000
RiskCategory = Literal["low", "emergency", "self_harm", "medical", "extreme_diet", "dangerous_training", "input_limit", "review_unavailable", "out_of_scope"]
ControlledDisclaimer = Literal["General lifestyle guidance only.", "仅供一般生活方式参考。"]


class SafetyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, revalidate_instances="always")
    outcome: Literal["allow", "rewrite", "refuse"]
    risk_category: RiskCategory
    violations: tuple[RiskCategory, ...] = ()
    required_disclaimer: ControlledDisclaimer | None = None


class SafetyRefusal(ApplicationError):
    def __init__(self, decision: SafetyDecision, question: str = "") -> None:
        self.decision = decision
        super().__init__(
            code="SAFETY_REFUSAL",
            message=_safe_message(decision.risk_category, question),
            status_code=422,
            processing_mode="agent",
            action="Seek qualified help for medical or urgent concerns.",
            retryable=False,
        )


class SafetyReviewer(Protocol):
    def review(self, question: str, draft: str) -> SafetyDecision: ...


_RULES: tuple[tuple[RiskCategory, str], ...] = (
    ("emergency", r"胸痛|呼吸困难|昏厥|失去意识|chest pain|cannot breathe|can't breathe|difficulty breathing|unconscious"),
    ("self_harm", r"自杀|自残|结束生命|kill myself|hurt myself|end my life|suicid"),
    ("medical", r"诊断|确诊|你患有|服用|停药|处方|治疗|糖尿病|diagnos|you have (?:diabetes|cancer)|treat(?:ment)? (?:my|your|a|the)|prescrib|stop taking|inject|take\s+\d+(?:\.\d+)?\s*(?:mg|tablets?)"),
    ("extreme_diet", r"绝食|催吐|泻药|starv(?:e|ing|ation)|purge|laxative|(?:每日|每天|只吃|daily|per day)[^\n]{0,24}(?:[1-7]\d\d|\d\d)\s*(?:卡|大卡|kcal|calories)|(?:[1-7]\d\d|\d\d)\s*(?:kcal|calories)[^\n]{0,16}(?:daily|per day)"),
    ("dangerous_training", r"忍痛|带伤训练|剧痛.*(?:练|训练)|through (?:severe |sharp )?pain|ignore (?:the )?pain|max(?:imum)? lift.*injur"),
    ("out_of_scope", r"(?:write|draft).{0,30}(?:real estate|legal|lease) contract|(?:recommend|choose).{0,20}(?:stocks|investment)|(?:起草|撰写).{0,12}(?:合同|法律文件)|(?:推荐|制定).{0,12}(?:股票|投资|买卖策略)"),
)


def _category(text: str) -> RiskCategory:
    # Do not mistake the fixed negative disclaimer for medical advice.
    text = re.sub(r"(?:do not|don't|does not|cannot) provide medical diagnosis|不提供医疗诊断", "", text, flags=re.I)
    for category, pattern in _RULES:
        if re.search(pattern, text, re.I):
            return category
    return "low"


def _safe_message(category: RiskCategory, question: str) -> str:
    chinese = bool(re.search(r"[\u3400-\u9fff]", question))
    if category == "out_of_scope":
        return "我可以帮助你了解饮食、训练和一般生活方式；此请求超出本工具的能力范围。" if chinese else "I can help with nutrition, training and general lifestyle information; this request is outside this tool's scope."
    if category in ("emergency", "self_harm"):
        return (
            "请先暂停训练。如果存在紧急危险，请立即联系当地急救服务，并请身边可信任的人陪伴。此工具不能处理急症或自伤危机。"
            if chinese else
            "Pause training. If there is immediate danger, contact local emergency services and ask someone you trust to stay with you. This tool cannot manage emergencies or self-harm crises."
        )
    return (
        "我只能提供一般生活方式建议。当前内容需要专业评估，不能据此进行诊断、用药、极端节食或危险训练。请咨询合格专业人员。"
        if chinese else
        "I can provide general lifestyle information only. This content needs qualified professional review; do not use it for diagnosis, medication, extreme dieting or dangerous training."
    )


def check_input(question: str) -> SafetyDecision:
    if not isinstance(question, str) or len(question) > MAX_QUESTION_CHARS:
        raise SafetyRefusal(SafetyDecision(outcome="refuse", risk_category="input_limit", violations=("input_limit",)))
    category = _category(question)
    decision = SafetyDecision(outcome="allow" if category == "low" else "refuse", risk_category=category,
                              violations=() if category == "low" else (category,))
    if decision.outcome == "refuse":
        raise SafetyRefusal(decision, question)
    return decision


class RuleSafetyReviewer:
    def review(self, question: str, draft: str) -> SafetyDecision:
        category = _category(draft)
        return SafetyDecision(outcome="allow" if category == "low" else "rewrite", risk_category=category,
                              violations=() if category == "low" else (category,))


def review_output(question: str, draft: str, *, reviewer: SafetyReviewer | None = None) -> tuple[str, SafetyDecision]:
    check_input(question)
    hard_decision = RuleSafetyReviewer().review(question, draft)
    if hard_decision.outcome != "allow":
        return _safe_message(hard_decision.risk_category, question), hard_decision
    try:
        decision = reviewer.review(question, draft) if reviewer is not None else hard_decision
        if not isinstance(decision, SafetyDecision):
            raise ValueError("Invalid safety decision")
        decision = SafetyDecision.model_validate(decision)
        if decision.outcome == "allow" and decision.risk_category != "low":
            raise ValueError("Inconsistent safety decision")
    except Exception:
        decision = SafetyDecision(outcome="rewrite", risk_category="review_unavailable", violations=("review_unavailable",))
    if decision.outcome == "refuse":
        raise SafetyRefusal(decision, question)
    if decision.outcome == "rewrite":
        return _safe_message(decision.risk_category, question), decision
    if decision.required_disclaimer:
        # A reviewer-provided disclaimer is output too, so enforce the hard rules.
        if _category(decision.required_disclaimer) != "low":
            return _safe_message("medical", question), SafetyDecision(outcome="rewrite", risk_category="medical", violations=("medical",))
        draft = f"{draft}\n\n{decision.required_disclaimer}"
    return draft, decision
