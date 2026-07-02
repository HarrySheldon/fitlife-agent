from __future__ import annotations

from pydantic import BaseModel


class PlannerRoute(BaseModel):
    intent: str
    needs_meal_analysis: bool = False
    needs_workout_analysis: bool = False
    needs_retrieval: bool = False
    needs_plan: bool = False
    needs_report: bool = False


def plan_route(question: str) -> PlannerRoute:
    text = question.lower()
    has_meal = any(token in text for token in ["蛋白", "热量", "饮食", "一餐", "吃", "calorie", "protein"])
    has_workout = any(token in text for token in ["训练", "肌群", "训练量", "workout", "exercise"])
    asks_plan = any(token in text for token in ["下周", "安排", "计划", "plan"])
    asks_report = any(token in text for token in ["周报", "总结", "报告", "summary"])
    asks_replacement = any(token in text for token in ["替代", "不想吃", "换成", "replace"])
    asks_knowledge = any(token in text for token in ["原则", "建议", "注意", "怎么", "如何"]) or asks_replacement

    if asks_report:
        return PlannerRoute(
            intent="weekly_report",
            needs_meal_analysis=True,
            needs_workout_analysis=True,
            needs_retrieval=True,
            needs_report=True,
        )
    if asks_plan:
        return PlannerRoute(
            intent="plan_generation",
            needs_meal_analysis=has_meal,
            needs_workout_analysis=True,
            needs_retrieval=True,
            needs_plan=True,
        )
    if has_meal and has_workout:
        return PlannerRoute(
            intent="mixed",
            needs_meal_analysis=True,
            needs_workout_analysis=True,
            needs_retrieval=asks_knowledge,
        )
    if has_meal and not asks_replacement:
        return PlannerRoute(intent="meal_analysis", needs_meal_analysis=True, needs_retrieval=asks_knowledge)
    if has_workout:
        return PlannerRoute(intent="workout_analysis", needs_workout_analysis=True, needs_retrieval=asks_knowledge)
    return PlannerRoute(intent="knowledge_qa", needs_retrieval=True)
