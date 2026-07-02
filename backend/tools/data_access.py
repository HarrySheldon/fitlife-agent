from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from backend.config import get_settings
from backend.schemas import EvalCase, UserProfile
from backend.tools.profile_loader import load_profile, save_profile


def data_path(filename: str) -> Path:
    return get_settings().data_dir / filename


def read_meals() -> pd.DataFrame:
    path = data_path("meals.csv")
    if not path.exists():
        return pd.DataFrame(columns=["date", "meal", "food", "amount", "calories", "protein", "carbs", "fat"])
    return pd.read_csv(path)


def read_workouts() -> pd.DataFrame:
    path = data_path("workouts.csv")
    if not path.exists():
        return pd.DataFrame(
            columns=["date", "type", "exercise", "muscle_group", "sets", "reps", "weight", "duration_min"]
        )
    return pd.read_csv(path)


def read_profile() -> UserProfile:
    return load_profile(data_path("user_profile.json"))


def write_profile(profile: UserProfile) -> None:
    save_profile(data_path("user_profile.json"), profile)


def read_eval_cases() -> list[EvalCase]:
    path = data_path("eval_questions.json")
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [EvalCase.model_validate(item) for item in raw]
