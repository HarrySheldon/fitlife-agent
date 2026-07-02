from __future__ import annotations


def write_answer(state: dict) -> str:
    intent = state.get("intent")
    tool_results = state.get("tool_results", {})
    docs = state.get("retrieved_docs", [])
    sources = sorted({doc["source"] for doc in docs})

    if intent == "meal_analysis":
        meal = tool_results.get("meal_analysis", {})
        return "\n".join(
            [
                "## 饮食分析",
                meal.get("summary", "暂无饮食分析。"),
                f"- 一周平均热量：{meal.get('weekly_average_calories', 0)} kcal",
                f"- 一周平均蛋白质：{meal.get('weekly_average_protein', 0)} g",
                f"- 蛋白质达标：{'是' if meal.get('protein_target_met') else '否'}",
            ]
        )
    if intent == "workout_analysis":
        workout = tool_results.get("workout_analysis", {})
        return "\n".join(
            [
                "## 训练分析",
                workout.get("summary", "暂无训练分析。"),
                f"- 训练类型分布：{workout.get('type_distribution', {})}",
                f"- 训练容量变化：{workout.get('week_over_week_volume_change', 0)}",
            ]
        )
    if intent == "weekly_report":
        report = tool_results.get("weekly_report", {})
        sections = "\n".join(f"### {item['title']}\n{item['content']}" for item in report.get("sections", []))
        checklist = "\n".join(f"- {item}" for item in report.get("checklist", []))
        return f"## 周报\n{sections}\n\n### 可执行清单\n{checklist}"
    if intent == "plan_generation":
        plan = tool_results.get("generated_plan", {})
        validation = plan.get("validation", {})
        warnings = validation.get("warnings", []) + validation.get("violations", [])
        warning_text = "\n".join(f"- {item}" for item in warnings) or "- 暂无明显风险。"
        return "\n".join(
            [
                "## 下周饮食与训练计划",
                "以下建议仅作一般生活方式管理参考，不构成医疗建议。",
                f"- 每日热量目标：{plan.get('diet_plan', {}).get('daily_calorie_target')} kcal",
                f"- 每日蛋白质目标：{plan.get('diet_plan', {}).get('daily_protein_target')} g",
                "### 风险校验",
                warning_text,
            ]
        )
    source_text = f"\n\n来源：{', '.join(sources)}" if sources else ""
    snippets = "\n".join(f"- {doc['text'][:160]}" for doc in docs[:3])
    return f"## 知识库回答\n{snippets}\n\n可替代选择应优先满足蛋白质目标、饮食偏好和过敏限制。{source_text}"
