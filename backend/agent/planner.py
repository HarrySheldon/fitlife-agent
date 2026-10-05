from __future__ import annotations

import sys

from pydantic import BaseModel


class _RouteFields(BaseModel):
    """The planner's routing decision.

    The per-domain analysis switches are *derived from the analysis registry* in
    :mod:`backend.agent.route_contract`, not enumerated here. Without that
    derivation a new domain would need an edit to this class before the planner
    could even ask for it.

    The switches that remain are generation-level capabilities: they select the
    deterministic generator and validator, which are workflow stages rather than
    configurable analyses.
    """

    intent: str
    needs_retrieval: bool = False
    needs_plan: bool = False
    needs_report: bool = False


def plan_route(question: str) -> "_RouteFields":
    """Deterministic fallback planner, used when no model connection is enabled."""
    # Resolved through this module's lazy export: the per-analysis switches live on
    # the registry-derived model, not on the leaf field container below.
    route = sys.modules[__name__].PlannerRoute
    text = question.lower()
    has_meal = any(token in text for token in ["蛋白", "热量", "饮食", "一餐", "吃", "calorie", "protein"])
    has_workout = any(token in text for token in ["训练", "肌群", "训练量", "workout", "exercise"])
    asks_plan = any(token in text for token in ["下周", "安排", "计划", "plan"])
    asks_report = any(token in text for token in ["周报", "总结", "报告", "summary"])
    asks_replacement = any(token in text for token in ["替代", "不想吃", "换成", "replace"])
    asks_knowledge = any(token in text for token in ["原则", "建议", "注意", "怎么", "如何"]) or asks_replacement

    if asks_report:
        return route(
            intent="weekly_report",
            needs_meal_analysis=True,
            needs_workout_analysis=True,
            needs_retrieval=True,
            needs_report=True,
        )
    if asks_plan:
        return route(
            intent="plan_generation",
            needs_meal_analysis=has_meal,
            needs_workout_analysis=True,
            needs_retrieval=True,
            needs_plan=True,
        )
    if has_meal and has_workout:
        return route(
            intent="mixed",
            needs_meal_analysis=True,
            needs_workout_analysis=True,
            needs_retrieval=asks_knowledge,
        )
    if has_meal and not asks_replacement:
        return route(intent="meal_analysis", needs_meal_analysis=True, needs_retrieval=asks_knowledge)
    if has_workout:
        return route(intent="workout_analysis", needs_workout_analysis=True, needs_retrieval=asks_knowledge)
    return route(intent="knowledge_qa", needs_retrieval=True)


def __getattr__(name: str):
    """Expose the registry-derived route model under this module (PEP 562).

    Resolved lazily so that ``backend.agent.planner`` stays a leaf module: the
    derived contract imports this module, so a module-level import here would
    close a cycle. Consumers that need the full, derived contract can keep using
    ``from backend.agent.planner import PlannerRoute``.
    """
    if name == "PlannerRoute":
        from backend.agent.route_contract import PlannerRoute as derived

        return derived
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
