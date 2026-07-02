from __future__ import annotations


def validate_generated_plan(plan: dict, profile: dict) -> dict:
    violations: list[str] = []
    warnings: list[str] = []
    repair_suggestions: list[str] = []

    diet = plan.get("diet_plan") or {}
    workout = plan.get("workout_plan") or {}
    calories = float(diet.get("daily_calorie_target") or 0)
    protein = float(diet.get("daily_protein_target") or 0)
    weight = float(profile.get("weight_kg") or 0)
    restrictions = [str(item).lower() for item in profile.get("allergies_or_restrictions", [])]
    meals_text = " ".join(str(item).lower() for item in diet.get("meals", []))

    if calories < 1200:
        violations.append("饮食计划热量明显过低，低于 MVP 安全下限 1200 kcal。")
        repair_suggestions.append("将每日热量提高到用户目标附近，并优先减少高热量零食而不是极端节食。")
    elif calories < float(profile.get("daily_calorie_target") or 0) * 0.75:
        warnings.append("饮食计划热量明显低于用户目标，需要说明这是保守建议。")

    if weight and protein < weight * 1.2:
        violations.append("蛋白质目标和用户体重不匹配，低于 1.2 g/kg 的基础训练建议。")
        repair_suggestions.append("根据体重把蛋白质提高到更合理区间。")

    for restriction in restrictions:
        if restriction and restriction in meals_text:
            violations.append(f"饮食计划违反用户过敏或限制：{restriction}。")
            repair_suggestions.append(f"替换所有包含 {restriction} 的餐食。")

    training_days = int(workout.get("weekly_training_days") or len(workout.get("days", [])))
    if training_days > 6:
        violations.append("训练频率过高，超过每周 6 天。")
        repair_suggestions.append("减少训练天数，并加入低强度或休息日。")
    if training_days < 2:
        warnings.append("训练频率偏低，可能不足以支持目标。")

    days = workout.get("days", [])
    consecutive_high = 0
    for day in days:
        intensity = str(day.get("intensity", "")).lower()
        if intensity == "high":
            consecutive_high += 1
            if consecutive_high >= 3:
                violations.append("训练计划连续安排高强度训练。")
                repair_suggestions.append("在高强度训练之间插入休息日或中低强度训练。")
                break
        else:
            consecutive_high = 0

    if not workout.get("rest_days"):
        violations.append("训练计划没有包含休息日。")
        repair_suggestions.append("至少加入 1-2 天休息日。")

    if not diet or not workout:
        violations.append("输出缺少 diet_plan 或 workout_plan 结构。")

    return {
        "passed": not violations,
        "warnings": warnings,
        "violations": violations,
        "repair_suggestions": repair_suggestions,
    }
