from __future__ import annotations

from backend.agent.validator import validate_generated_plan


def generate_weekly_report(profile: dict, meal_result: dict, workout_result: dict) -> dict:
    checklist = [
        "每天记录三餐和加餐，避免漏记高热量零食。",
        "每餐优先安排一份优质蛋白。",
        "下周至少保留 1-2 天恢复日。",
    ]
    if not meal_result.get("protein_target_met"):
        checklist.insert(0, "把早餐或加餐补足 20-30g 蛋白质。")
    if workout_result.get("undertrained_muscle_groups"):
        groups = "、".join(workout_result["undertrained_muscle_groups"][:3])
        checklist.append(f"补齐训练覆盖不足的肌群：{groups}。")

    return {
        "title": "FitLife Weekly Report",
        "sections": [
            {"title": "饮食概览", "content": meal_result.get("summary", "")},
            {"title": "训练概览", "content": workout_result.get("summary", "")},
            {
                "title": "主要问题",
                "content": "优先关注蛋白质达标、总热量稳定和训练肌群覆盖。",
            },
            {
                "title": "下周建议",
                "content": f"围绕 {profile.get('goal', 'maintenance')} 目标执行，保持可持续调整。",
            },
        ],
        "checklist": checklist,
    }


def generate_next_week_plan(profile: dict) -> dict:
    calorie_target = int(profile.get("daily_calorie_target", 2100))
    protein_target = int(profile.get("daily_protein_target", 130))
    frequency = int(profile.get("weekly_training_frequency", 4))
    no_chicken = any("chicken" in item or "鸡胸" in item for item in profile.get("diet_preferences", []))
    lunch_protein = "瘦牛肉饭或鱼肉饭" if no_chicken else "鸡胸肉糙米饭"
    training_days = min(max(frequency, 3), 5)

    plan = {
        "diet_plan": {
            "daily_calorie_target": calorie_target,
            "daily_protein_target": protein_target,
            "meals": [
                "早餐：燕麦、希腊酸奶、鸡蛋",
                f"午餐：{lunch_protein}、蔬菜",
                "晚餐：三文鱼或豆腐、土豆、沙拉",
                "加餐：乳清蛋白或无糖酸奶",
            ],
            "substitutions": ["鸡胸肉可替换为鱼、虾、瘦牛肉、鸡蛋、豆腐或低脂奶制品。"],
        },
        "workout_plan": {
            "weekly_training_days": training_days,
            "days": [
                {"day": "Mon", "type": "strength", "focus": "legs", "intensity": "medium", "exercises": ["squat", "lunge"]},
                {"day": "Tue", "type": "rest", "focus": "recovery", "intensity": "rest", "exercises": []},
                {"day": "Wed", "type": "strength", "focus": "push", "intensity": "high", "exercises": ["bench press", "overhead press"]},
                {"day": "Fri", "type": "strength", "focus": "pull", "intensity": "medium", "exercises": ["row", "lat pulldown"]},
                {"day": "Sun", "type": "cardio", "focus": "aerobic", "intensity": "low", "exercises": ["zone 2 run"]},
            ][: training_days + 1],
            "rest_days": ["Tue", "Sat"],
            "notes": ["力量动作每个 3-4 组，每组 8-12 次；高强度日之间保留恢复。"],
        },
    }
    plan["validation"] = validate_generated_plan(plan, profile)
    return plan
