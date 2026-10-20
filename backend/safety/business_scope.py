"""Conservative product admission, independent of the health risk gate.

Unknown requests go to the planner. Model suggestions never grant permission or
provide the user text retained by this policy.

This is a bounded deterministic fallback, not a general natural-language intent
classifier. Unsupported phrasing clarifies after planning; no live classification
accuracy is asserted. Existing risk and injection gates remain independent.
"""
from dataclasses import dataclass
import re
from typing import Literal


@dataclass(frozen=True)
class ScopeDecision:
    scope: Literal["in_scope", "out_of_scope", "mixed", "unclear"]
    allowed_subtasks: tuple[str, ...] = ()
    refusal_code: str | None = None
    needs_clarification: bool = False


def is_auxiliary_request(question: str) -> bool:
    """Only explicit greetings and product help qualify for the fixed response."""
    return bool(re.fullmatch(r"你好[！!。]*|您好[！!。]*|hi[!.]*|hello[!.]*", question.strip(), re.I)
                or re.search(r"(?:FitLife).*(?:使用|功能|help)|(?:怎么|如何)使用(?:这个应用|FitLife)", question, re.I))


def is_closed_followup(question: str) -> bool:
    return bool(re.fullmatch(r"(?:为什么|为什麼|再详细一点|详细解释一下|继续解释|why|more detail(?:s)?|explain more)[？?。. !]*", question.strip(), re.I))


def followup_policy_question(question: str, history: tuple[dict, ...]) -> str:
    """Resolve only closed, non-actionable continuation forms, never new goals.

    This reuses an independently admitted prior user request, not the model's
    answer. New/mixed/out-of-scope instructions cannot borrow its permission.
    """
    if not is_closed_followup(question):
        return question
    for message in reversed(history):
        if message.get("role") == "user":
            if message.get("admitted_scope") is True:
                return "Explain fitness"
            previous = message.get("body", "")
            if isinstance(previous, str) and decide_business_scope(previous).scope == "in_scope":
                return previous
            if isinstance(previous, str) and is_closed_followup(previous):
                continue
            break
    return question


_HEALTH = r"健身|训练|訓練|运动|運動|饮食|飲食|蛋白|热量|熱量|减脂|減脂|久坐|睡眠|fitness|workouts?|nutrition|exercise|protein|calorie|diet|training|meals?|sleep"
# Commit each token before trying the next one: 我的 must never be repartitioned
# as 我 + 的 repeatedly when the eventual health noun does not match.
_ZH_MODIFIERS = r"(?>(?:我的?|今天的?|这周的?|下周的?|一般|日常|每周|每日|适度|规律|继续|和|与|及|的))*"
_EN_MODIFIERS = r"(?:(?:my|the|a|with|next|today's|weekly|daily|active|persisted|deterministic|general|practical|recent|user's|remaining)\s+)*"
_FOOD = r"鸡胸肉|鸡肉|鱼肉|牛肉|豆腐|鸡蛋|chicken breast|chicken|fish|beef|tofu|eggs?"


def _supported_detail_question(text: str) -> bool:
    """Closed grammatical forms for intake, food substitution and app reports."""
    return bool(re.fullmatch(
        rf"(?:did I (?:hit|meet|reach) my (?:protein|calorie|nutrition) (?:target|goal)(?: (?:this|last) week)?"
        rf"|how (?:is|was) my (?:protein|calorie|nutrition) intake(?: (?:today|this week|last week))?"
        rf"|what can (?:replace|substitute for) (?:{_FOOD}) for (?:protein|nutrition)"
        rf"|(?:create|generate|show) (?:a |my |the )?weekly (?:summary |fitness |nutrition |training )?report"
        rf"|我(?:不想|不能|不喜欢)吃(?:{_FOOD})[，,]\s*(?:有)?(?:什么|哪些)(?:替代|替换)(?:食物|选择)?)[？?。.]*",
        text.strip(), re.I,
    ))


def _health_request(text: str) -> bool:
    """Recognize supported request shapes, rather than a topic mentioned anywhere.

    Every nonempty clause must itself be health directed or a limited context
    fragment. An arbitrary preceding goal cannot borrow a later health word.
    """
    if re.search(r"为了|以便|从而|让我|用来|然后|之后用|以后继续|顺便|so that|in order to|afterwards", text, re.I):
        return False
    if _supported_detail_question(text):
        return True
    clauses = [part.strip() for part in re.split(r"[，,；;。.?!？！]", text) if part.strip()]
    for clause in clauses:
        if not re.search(_HEALTH, clause, re.I):
            return False
        for coordinated in re.split(r"\band\b|和|与|及", clause, flags=re.I)[1:]:
            if not re.match(rf"\s*(?:{_EN_MODIFIERS}|{_ZH_MODIFIERS})(?:{_HEALTH})", coordinated, re.I):
                return False
        requested = re.match(r"(?:请|請)?(?:帮我|幫我|我想|我要|请|請)(.*)", clause)
        if requested and not re.match(
            rf"(?:怎么|怎樣|如何|安排|了解|解释|分析|调整|总结|计划|{_HEALTH})", requested.group(1)
        ):
            return False
        chinese = (
            re.match(rf"(?:(?:工作|上班|写代码)?久坐)?(?:怎么|怎樣|如何)?(?:安排|了解|解释|调整|总结|分析|计划|建议|注意){_ZH_MODIFIERS}(?:{_HEALTH})", requested.group(1) if requested else clause, re.I)
            or re.match(rf"{_ZH_MODIFIERS}(?:{_HEALTH}).*(?:怎么|怎樣|如何|多少|够了?吗|可以吗|建议|注意|安排|计划|状态|狀態)", clause, re.I)
        )
        english = re.match(
            rf"(?:(?:help me )?(?:understand|explain|review|interpret|suggest|create|adjust|plan|analyze)\s+{_EN_MODIFIERS}(?:{_HEALTH})"
            rf"|how (?:did|do|can|should) I (?:sleep|exercise|train|eat)\b"
            rf"|(?:{_HEALTH}) (?:advice|question))", clause, re.I)
        if not (chinese or english):
            return False
    return bool(clauses)


def decide_business_scope(question: str, *, planner_consulted: bool = False) -> ScopeDecision:
    text = question.strip()
    # Instruction attacks belong to the injection gate, never this admission rule.
    if re.search(r"忽略.*(?:指令|规则)|系统提示|ignore.*instructions|system prompt", text, re.I):
        return ScopeDecision("unclear", needs_clarification=planner_consulted)
    health = _health_request(text)
    mentions_health = bool(re.search(_HEALTH, text, re.I))
    irrelevant = bool(re.search(r"(?:帮我|请|如何|怎么).*(?:选股票|推荐股票|炒股|写代码|写程序)|(?:pick|recommend|choose) stocks|write (?:code|a program)", text, re.I)
                      or re.fullmatch(r"(?:which|what) stocks (?:should|can|could) I (?:buy|sell)[?!.]*", text, re.I))
    if mentions_health and irrelevant:
        if re.search(r"另外单独问[:：]|两个互不相关的问题[:：]", text) and not re.search(r"为了|以便|从而|先|然后|这样|让我|有精力|用来|以后|之后|以.*为目标|so that|in order|first|then", text, re.I):
            separate = re.sub(r"两个互不相关的问题[:：]", "", text, count=1)
            clauses = tuple(part.strip() for part in re.split(r"[；;]|另外单独问[:：]", separate) if part.strip())
            if len(clauses) > 1:
                decisions = tuple(decide_business_scope(part) for part in clauses)
                if all(item.scope in {"in_scope", "out_of_scope"} for item in decisions):
                    kept = tuple(part for part, item in zip(clauses, decisions) if item.scope == "in_scope")
                    if kept:
                        return ScopeDecision("mixed", kept)
        # Semantic independence is not inferred from punctuation. A normal clause
        # could be an enabling step toward the other goal; clarify before tools.
        return ScopeDecision("mixed", needs_clarification=True)
    if health:
        return ScopeDecision("in_scope", (text,))
    if irrelevant:
        return ScopeDecision("out_of_scope", refusal_code="BUSINESS_OUT_OF_SCOPE")
    if is_auxiliary_request(text):
        return ScopeDecision("in_scope", (text,))
    return ScopeDecision("unclear", needs_clarification=planner_consulted)
