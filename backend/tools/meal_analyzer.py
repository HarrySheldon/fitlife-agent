from __future__ import annotations

import pandas as pd


REQUIRED_MEAL_COLUMNS = ["date", "meal", "food", "amount", "calories", "protein", "carbs", "fat"]


def validate_meal_columns(frame: pd.DataFrame) -> None:
    missing = [column for column in REQUIRED_MEAL_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing meal columns: {', '.join(missing)}")


def analyze_meals(frame: pd.DataFrame, calorie_target: float, protein_target: float) -> dict:
    validate_meal_columns(frame)
    if frame.empty:
        return _empty_meal_result()

    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"]).dt.strftime("%Y-%m-%d")
    for column in ["calories", "protein", "carbs", "fat"]:
        data[column] = pd.to_numeric(data[column], errors="coerce").fillna(0)

    grouped = data.groupby("date")[["calories", "protein", "carbs", "fat"]].sum().sort_index()
    daily_totals = {
        date: {metric: round(float(value), 2) for metric, value in row.items()}
        for date, row in grouped.to_dict(orient="index").items()
    }
    highest = data.sort_values("calories", ascending=False).iloc[0]
    weekly_average_calories = round(float(grouped["calories"].mean()), 2)
    weekly_average_protein = round(float(grouped["protein"].mean()), 2)
    protein_target_met = weekly_average_protein >= protein_target
    calorie_target_exceeded = weekly_average_calories > calorie_target

    summary = (
        f"本周期平均每日热量 {weekly_average_calories:g} kcal，"
        f"平均蛋白质 {weekly_average_protein:g} g。"
        f"蛋白质{'已达标' if protein_target_met else '未达标'}，"
        f"热量{'超过' if calorie_target_exceeded else '未超过'}目标。"
    )

    return {
        "daily_totals": daily_totals,
        "weekly_average_calories": weekly_average_calories,
        "weekly_average_protein": weekly_average_protein,
        "highest_calorie_food": {
            "date": str(highest["date"]),
            "meal": str(highest["meal"]),
            "food": str(highest["food"]),
            "calories": round(float(highest["calories"]), 2),
        },
        "protein_target_met": protein_target_met,
        "calorie_target_exceeded": calorie_target_exceeded,
        "summary": summary,
    }


def _empty_meal_result() -> dict:
    return {
        "daily_totals": {},
        "weekly_average_calories": 0,
        "weekly_average_protein": 0,
        "highest_calorie_food": None,
        "protein_target_met": False,
        "calorie_target_exceeded": False,
        "summary": "暂无饮食记录。",
    }
