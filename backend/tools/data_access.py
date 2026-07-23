from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from backend.config import get_settings
from backend.infrastructure.user_lifecycle import user_lifecycle_guard
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
    experience_level="novice",
    training_preference="mixed",
    target_mode="suggested",
)


def data_path(filename: str, user_id: str | None = None) -> Path:
    if user_id is None:
        return get_settings().data_dir / filename
    ensure_user_data(user_id)
    return get_settings().data_dir / "users" / user_id / filename


def ensure_user_data(user_id: str) -> Path:
    data_dir = get_settings().data_dir
    with user_lifecycle_guard(data_dir, user_id):
        return _ensure_user_data_unlocked(data_dir, user_id)


def _ensure_user_data_unlocked(data_dir: Path, user_id: str) -> Path:
    root = data_dir / "users" / user_id
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
    if user_id is None:
        save_profile(data_path("user_profile.json"), profile)
        return
    with user_lifecycle_guard(get_settings().data_dir, user_id):
        save_profile(data_path("user_profile.json", user_id), profile)


def update_profile_atomically(
    update: Callable[[UserProfile], UserProfile],
    user_id: str | None = None,
) -> UserProfile:
    if user_id is None:
        path = data_path("user_profile.json")
        updated = UserProfile.model_validate(update(load_profile(path)))
        save_profile(path, updated)
        return updated

    data_dir = get_settings().data_dir
    with user_lifecycle_guard(data_dir, user_id):
        root = _ensure_user_data_unlocked(data_dir, user_id)
        path = root / "user_profile.json"
        updated = UserProfile.model_validate(update(load_profile(path)))
        save_profile(path, updated)
        return updated


def append_meal(record: MealRecord, user_id: str | None = None) -> None:
    if user_id is None:
        _append_meal_unlocked(record, user_id)
        return
    with user_lifecycle_guard(get_settings().data_dir, user_id):
        _append_meal_unlocked(record, user_id)


def _append_meal_unlocked(record: MealRecord, user_id: str | None) -> None:
    path = data_path("meals.csv", user_id)
    frame = read_meals(user_id)
    frame = pd.concat([frame, pd.DataFrame([record.model_dump()])], ignore_index=True)
    frame.to_csv(path, index=False)


def append_workout(record: WorkoutRecord, user_id: str | None = None) -> None:
    if user_id is None:
        _append_workout_unlocked(record, user_id)
        return
    with user_lifecycle_guard(get_settings().data_dir, user_id):
        _append_workout_unlocked(record, user_id)


def _append_workout_unlocked(record: WorkoutRecord, user_id: str | None) -> None:
    path = data_path("workouts.csv", user_id)
    frame = read_workouts(user_id)
    frame = pd.concat([frame, pd.DataFrame([record.model_dump()])], ignore_index=True)
    frame.to_csv(path, index=False)


def write_data_bytes(filename: str, content: bytes, user_id: str | None = None) -> Path:
    if user_id is None:
        destination = data_path(filename)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return destination
    with user_lifecycle_guard(get_settings().data_dir, user_id):
        destination = data_path(filename, user_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return destination


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
