from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "backend" / "data"


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    generate_profile()
    generate_meals()
    generate_workouts()
    generate_eval_questions()


def generate_profile() -> None:
    profile = {
        "height_cm": 175,
        "weight_kg": 72,
        "age": 24,
        "gender": "male",
        "goal": "fat_loss",
        "weekly_training_frequency": 4,
        "diet_preferences": ["high_protein", "no_chicken_breast"],
        "allergies_or_restrictions": ["peanut"],
        "target_weight_kg": 68,
        "daily_calorie_target": 2100,
        "daily_protein_target": 130,
    }
    (DATA_DIR / "user_profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_meals() -> None:
    foods = [
        ("breakfast", "oats yogurt egg", "1 bowl", 520, 34, 64, 14),
        ("lunch", "beef rice vegetables", "1 plate", 720, 45, 82, 22),
        ("dinner", "salmon potato salad", "1 plate", 680, 42, 58, 26),
        ("snack", "greek yogurt fruit", "1 cup", 210, 18, 24, 4),
    ]
    start = date(2026, 6, 1)
    with (DATA_DIR / "meals.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["date", "meal", "food", "amount", "calories", "protein", "carbs", "fat"])
        for day_index in range(30):
            current = start + timedelta(days=day_index)
            for meal, food, amount, calories, protein, carbs, fat in foods:
                adjustment = (day_index % 5) * 15
                writer.writerow(
                    [current.isoformat(), meal, food, amount, calories + adjustment, protein, carbs, fat]
                )


def generate_workouts() -> None:
    workouts = [
        ("strength", "squat", "legs", 4, 8, 80, 55),
        ("strength", "bench press", "chest", 4, 8, 60, 50),
        ("strength", "row", "back", 4, 10, 55, 50),
        ("cardio", "zone 2 run", "full_body", 0, 0, 0, 35),
    ]
    start = date(2026, 6, 1)
    with (DATA_DIR / "workouts.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["date", "type", "exercise", "muscle_group", "sets", "reps", "weight", "duration_min"])
        for week in range(4):
            for offset, row in zip([0, 2, 4, 6], workouts):
                current = start + timedelta(days=week * 7 + offset)
                writer.writerow([current.isoformat(), *row])


def generate_eval_questions() -> None:
    cases = [
        ("我这周蛋白质吃够了吗？", "analyze_meals", None, ["蛋白质"]),
        ("帮我总结这周饮食问题。", "generate_weekly_report", "nutrition_guidelines.md", ["周报"]),
        ("这周我的训练量相比上周有提升吗？", "analyze_workouts", None, ["训练"]),
        ("我不想吃鸡胸肉，有什么替代？", "retrieve_knowledge", "meal_templates.md", ["替代"]),
        ("我想减脂，下周怎么安排训练？", "generate_next_week_plan", "fitness_rules.md", ["计划"]),
        ("找出最近热量最高的食物。", "analyze_meals", None, ["热量"]),
        ("下周饮食计划需要注意什么？", "generate_next_week_plan", "plan_rules.md", ["热量"]),
        ("训练计划需要休息日吗？", "retrieve_knowledge", "plan_rules.md", ["休息"]),
        ("减脂期应该只做有氧吗？", "retrieve_knowledge", "fitness_rules.md", ["力量"]),
        ("豆腐能替代肉类补蛋白吗？", "retrieve_knowledge", "meal_templates.md", ["蛋白"]),
        ("帮我生成一份周报。", "generate_weekly_report", "nutrition_guidelines.md", ["周报"]),
        ("我最近训练肌群覆盖够吗？", "analyze_workouts", None, ["肌群"]),
        ("这周平均热量是多少？", "analyze_meals", None, ["热量"]),
        ("每周训练四天怎么安排？", "generate_next_week_plan", "fitness_rules.md", ["训练"]),
        ("坚果适合作为加餐吗？", "retrieve_knowledge", "meal_templates.md", ["加餐"]),
        ("蛋白质目标怎么定？", "retrieve_knowledge", "nutrition_guidelines.md", ["蛋白质"]),
        ("维持期训练怎么做？", "retrieve_knowledge", "fitness_rules.md", ["维持"]),
        ("背部训练有哪些动作？", "retrieve_knowledge", "exercise_library.md", ["背部"]),
        ("计划会不会违反我的过敏限制？", "validate_plan", "plan_rules.md", ["限制"]),
        ("给我一份下周饮食建议。", "generate_next_week_plan", "meal_templates.md", ["饮食"]),
    ]
    payload = [
        {
            "question": question,
            "expected_tool": tool,
            "expected_retrieval_doc": doc,
            "expected_answer_format": "markdown",
            "expected_keywords": keywords,
        }
        for question, tool, doc, keywords in cases
    ]
    (DATA_DIR / "eval_questions.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
