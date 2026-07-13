from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import pandas as pd

from backend.schemas import AgentEntryRequest, AgentEntryResponse, DailyDetail, DailySummary, MealRecord, WorkoutRecord
from backend.tools.data_access import append_meal, append_workout, read_meals, read_workouts


def list_daily_summaries(start: str, end: str, user_id: str | None = None) -> list[DailySummary]:
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    meals = read_meals(user_id)
    workouts = read_workouts(user_id)
    summaries = []
    for current in _date_range(start_date, end_date):
        summaries.append(_summarize_day(current.isoformat(), meals, workouts))
    return summaries


def get_daily_detail(day: str, user_id: str | None = None) -> DailyDetail:
    return build_daily_detail(day, read_meals(user_id), read_workouts(user_id))


def build_daily_detail(day: str, meals: pd.DataFrame, workouts: pd.DataFrame) -> DailyDetail:
    day = _parse_date(day).isoformat()
    return DailyDetail(
        summary=_summarize_day(day, meals, workouts),
        meals=[MealRecord.model_validate(row) for row in _rows_for_date(meals, day)],
        workouts=[WorkoutRecord.model_validate(row) for row in _rows_for_date(workouts, day)],
    )


def create_meal(record: MealRecord, user_id: str | None = None) -> DailyDetail:
    append_meal(record, user_id)
    return get_daily_detail(record.date, user_id)


def create_workout(record: WorkoutRecord, user_id: str | None = None) -> DailyDetail:
    append_workout(record, user_id)
    return get_daily_detail(record.date, user_id)


def create_agent_entry(request: AgentEntryRequest, user_id: str | None = None) -> AgentEntryResponse:
    actions: list[str] = []
    day = _parse_date(request.date).isoformat()
    text = request.text.strip()
    calories = _first_number_before_unit(text, ["kcal", "千卡", "卡路里", "热量"])
    protein = _number_after_label(text, ["蛋白质", "蛋白", "protein"])
    duration = _first_number_before_unit(text, ["分钟", "min", "mins", "minute", "minutes"])

    if calories is not None or protein is not None:
        append_meal(
            MealRecord(
                date=day,
                meal="smart_log",
                food=_short_text(text),
                amount="parsed from text",
                calories=calories or 0,
                protein=protein or 0,
                carbs=0,
                fat=0,
            ),
            user_id,
        )
        actions.append("meal_record_created")

    if duration is not None or _looks_like_workout(text):
        append_workout(
            WorkoutRecord(
                date=day,
                type="cardio" if _looks_like_cardio(text) else "strength",
                exercise=_short_text(text),
                muscle_group="full_body",
                sets=0,
                reps=0,
                weight=0,
                duration_min=duration or 0,
            ),
            user_id,
        )
        actions.append("workout_record_created")

    return AgentEntryResponse(parsed_actions=actions, day=get_daily_detail(day, user_id))


def latest_activity_date(user_id: str | None = None) -> str:
    dates = []
    for frame in [read_meals(user_id), read_workouts(user_id)]:
        if not frame.empty and "date" in frame:
            dates.extend(str(value) for value in frame["date"].dropna().tolist())
    if dates:
        return sorted(dates)[-1]
    return date.today().isoformat()


def _summarize_day(day: str, meals: pd.DataFrame, workouts: pd.DataFrame) -> DailySummary:
    meal_rows = meals[meals["date"].astype(str) == day] if "date" in meals else pd.DataFrame()
    workout_rows = workouts[workouts["date"].astype(str) == day] if "date" in workouts else pd.DataFrame()
    return DailySummary(
        date=day,
        calories=_sum(meal_rows, "calories"),
        protein=_sum(meal_rows, "protein"),
        carbs=_sum(meal_rows, "carbs"),
        fat=_sum(meal_rows, "fat"),
        meal_count=int(len(meal_rows)),
        training_sessions=int(len(workout_rows)),
        training_duration_min=_sum(workout_rows, "duration_min"),
        has_data=bool(len(meal_rows) or len(workout_rows)),
    )


def _rows_for_date(frame: pd.DataFrame, day: str) -> list[dict]:
    if frame.empty or "date" not in frame:
        return []
    rows = frame[frame["date"].astype(str) == day]
    return rows.fillna(0).to_dict(orient="records")


def _sum(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame:
        return 0
    return float(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())


def _date_range(start: date, end: date):
    if end < start:
        start, end = end, start
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _first_number_before_unit(text: str, units: list[str]) -> float | None:
    unit_pattern = "|".join(re.escape(unit) for unit in units)
    patterns = [
        rf"(\d+(?:\.\d+)?)\s*(?:{unit_pattern})",
        rf"(?:{unit_pattern})[^\d]*(\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _number_after_label(text: str, labels: list[str]) -> float | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?:{label_pattern})[^\d]*(\d+(?:\.\d+)?)", text, flags=re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def _looks_like_workout(text: str) -> bool:
    keywords = ["训练", "跑步", "力量", "深蹲", "卧推", "workout", "run", "squat", "press"]
    return any(keyword.lower() in text.lower() for keyword in keywords)


def _looks_like_cardio(text: str) -> bool:
    keywords = ["跑", "有氧", "cardio", "run", "walk", "bike"]
    return any(keyword.lower() in text.lower() for keyword in keywords)


def _short_text(text: str) -> str:
    return text[:80]
