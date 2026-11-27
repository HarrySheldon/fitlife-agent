"""Deterministic query domain/type classification for metadata-filtered RAG."""
from __future__ import annotations

import re
from dataclasses import dataclass

_NUTRITION_RE = re.compile(
    r"饮食|营养|蛋白|热量|卡路里|碳水|脂肪|加餐|替代|鸡胸|早餐|午餐|晚餐|水分|喝水|nutrition|protein|calorie|carb|fat|meal|diet|hydration",
    re.I,
)
_TRAINING_RE = re.compile(
    r"训练|动作|深蹲|卧推|硬拉|划船|有氧|力量|组数|次数|RPE|减量|deload|肩|膝|肌群|增肌|减脂训练|workout|exercise|training|squat|bench|deadlift|cardio",
    re.I,
)
_TABLE_HINT_RE = re.compile(
    r"多少克|换算|替换|替代|对比|表格|周容量|几组|标准|范围|列表|ratio|table|swap|per kg",
    re.I,
)


@dataclass(frozen=True)
class QueryPlan:
    domain: str | None
    doc_type_hint: str | None = None
    strict_filter: bool = False


def classify_query(query: str, *, explicit_scope: str | None = None) -> QueryPlan:
    """Classify domain & doc-type hint; honor explicit non-'general' scope strictly."""
    doc_type_hint = "table" if _TABLE_HINT_RE.search(query) else None
    if explicit_scope in {"training", "nutrition"}:
        return QueryPlan(domain=explicit_scope, doc_type_hint=doc_type_hint, strict_filter=True)

    has_nutrition = bool(_NUTRITION_RE.search(query))
    has_training = bool(_TRAINING_RE.search(query))
    if has_nutrition and not has_training:
        return QueryPlan(domain="nutrition", doc_type_hint=doc_type_hint, strict_filter=False)
    if has_training and not has_nutrition:
        return QueryPlan(domain="training", doc_type_hint=doc_type_hint, strict_filter=False)
    return QueryPlan(domain=None, doc_type_hint=doc_type_hint, strict_filter=False)
