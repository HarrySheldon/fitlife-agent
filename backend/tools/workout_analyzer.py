from __future__ import annotations

import pandas as pd


REQUIRED_WORKOUT_COLUMNS = [
    "date",
    "type",
    "exercise",
    "muscle_group",
    "sets",
    "reps",
    "weight",
    "duration_min",
]
EXPECTED_MUSCLE_GROUPS = {"legs", "chest", "back", "shoulders", "core"}


def validate_workout_columns(frame: pd.DataFrame) -> None:
    missing = [column for column in REQUIRED_WORKOUT_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing workout columns: {', '.join(missing)}")


def analyze_workouts(frame: pd.DataFrame) -> dict:
    validate_workout_columns(frame)
    if frame.empty:
        return _empty_workout_result()

    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"])
    data["week"] = data["date"].dt.strftime("%G-W%V")
    for column in ["sets", "reps", "weight", "duration_min"]:
        data[column] = pd.to_numeric(data[column], errors="coerce").fillna(0)
    data["strength_volume"] = data["sets"] * data["reps"] * data["weight"]

    weekly_counts = data.groupby("week").size().sort_index()
    weekly_duration = data.groupby("week")["duration_min"].sum().sort_index()
    weekly_volume = data.groupby("week")["strength_volume"].sum().sort_index()
    type_distribution = data["type"].value_counts().to_dict()
    trained_groups = set(data["muscle_group"].dropna().astype(str).str.lower())
    undertrained = sorted(EXPECTED_MUSCLE_GROUPS - trained_groups)
    volume_values = [float(value) for value in weekly_volume.tolist()]
    if len(volume_values) >= 2:
        week_over_week = round(volume_values[-1] - volume_values[-2], 2)
    elif volume_values:
        week_over_week = round(volume_values[-1], 2)
    else:
        week_over_week = 0

    total_duration = round(float(data["duration_min"].sum()), 2)
    summary = (
        f"本周期共记录 {len(data)} 次训练，总时长 {total_duration:g} 分钟，"
        f"力量训练容量 {float(data['strength_volume'].sum()):g}。"
    )

    return {
        "weekly_training_counts": {week: int(count) for week, count in weekly_counts.items()},
        "type_distribution": {key: int(value) for key, value in type_distribution.items()},
        "weekly_duration_min": {week: round(float(value), 2) for week, value in weekly_duration.items()},
        "total_strength_volume": round(float(data["strength_volume"].sum()), 2),
        "undertrained_muscle_groups": undertrained,
        "week_over_week_volume_change": week_over_week,
        "summary": summary,
    }


def _empty_workout_result() -> dict:
    return {
        "weekly_training_counts": {},
        "type_distribution": {},
        "weekly_duration_min": {},
        "total_strength_volume": 0,
        "undertrained_muscle_groups": sorted(EXPECTED_MUSCLE_GROUPS),
        "week_over_week_volume_change": 0,
        "summary": "暂无训练记录。",
    }
