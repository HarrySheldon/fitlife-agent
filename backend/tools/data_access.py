from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd

from backend.config import get_settings
from backend.schemas import EvalCase, MealRecord, UserProfile, WorkoutRecord
from backend.tools.profile_loader import load_profile, save_profile


MEAL_COLUMNS = ["date", "meal", "food", "amount", "calories", "protein", "carbs", "fat"]
WORKOUT_COLUMNS = ["date", "type", "exercise", "muscle_group", "sets", "reps", "weight", "duration_min"]


DEFAULT_PROFILE = UserProfile(
    height_cm=175,
    weight_kg=72,
    age=24,
    gender="male",
    goal="fat_loss",
    weekly_training_frequency=4,
    diet_preferences=["high_protein"],
    allergies_or_restrictions=[],
    target_weight_kg=68,
    daily_calorie_target=2100,
    daily_protein_target=130,
)


def data_path(filename: str, user_id: str | None = None) -> Path:
    if user_id is None:
        return get_settings().data_dir / filename
    ensure_user_data(user_id)
    return get_settings().data_dir / "users" / user_id / filename


def ensure_user_data(user_id: str) -> Path:
    root = get_settings().data_dir / "users" / user_id
    root.mkdir(parents=True, exist_ok=True)
    _ensure_profile(root / "user_profile.json")
    _ensure_csv(root / "meals.csv", MEAL_COLUMNS)
    _ensure_csv(root / "workouts.csv", WORKOUT_COLUMNS)
    return root


def read_meals(user_id: str | None = None) -> pd.DataFrame:
    path = data_path("meals.csv", user_id)
    if not path.exists():
        return pd.DataFrame(columns=MEAL_COLUMNS)
    return pd.read_csv(path)


def read_workouts(user_id: str | None = None) -> pd.DataFrame:
    path = data_path("workouts.csv", user_id)
    if not path.exists():
        return pd.DataFrame(columns=WORKOUT_COLUMNS)
    return pd.read_csv(path)


def read_profile(user_id: str | None = None) -> UserProfile:
    return load_profile(data_path("user_profile.json", user_id))


def write_profile(profile: UserProfile, user_id: str | None = None) -> None:
    save_profile(data_path("user_profile.json", user_id), profile)


def append_meal(record: MealRecord, user_id: str | None = None) -> None:
    path = data_path("meals.csv", user_id)
    frame = read_meals(user_id)
    frame = pd.concat([frame, pd.DataFrame([record.model_dump()])], ignore_index=True)
    frame.to_csv(path, index=False)


def append_workout(record: WorkoutRecord, user_id: str | None = None) -> None:
    path = data_path("workouts.csv", user_id)
    frame = read_workouts(user_id)
    frame = pd.concat([frame, pd.DataFrame([record.model_dump()])], ignore_index=True)
    frame.to_csv(path, index=False)


def read_eval_cases() -> list[EvalCase]:
    path = data_path("eval_questions.json")
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [EvalCase.model_validate(item) for item in raw]


def _ensure_profile(path: Path) -> None:
    if path.exists():
        return
    source = get_settings().data_dir / "user_profile.json"
    if source.exists():
        shutil.copyfile(source, path)
        return
    save_profile(path, DEFAULT_PROFILE)


def _ensure_csv(path: Path, columns: list[str]) -> None:
    if path.exists():
        return
    source = get_settings().data_dir / path.name
    if source.exists():
        pd.DataFrame(columns=columns).to_csv(path, index=False)
        return
    pd.DataFrame(columns=columns).to_csv(path, index=False)
