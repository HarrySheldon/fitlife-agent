import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.tools.profile_loader import load_profile, save_profile
from backend.schemas import UserProfile


TEST_PROFILE_PATH = Path("backend/data/profile_loader_test.json")


def test_load_and_save_profile_roundtrip():
    profile = UserProfile(
        height_cm=175,
        weight_kg=72,
        age=24,
        gender="male",
        goal="fat_loss",
        weekly_training_frequency=4,
        diet_preferences=["high_protein", "no_chicken_breast"],
        allergies_or_restrictions=["peanut"],
        target_weight_kg=68,
        daily_calorie_target=2100,
        daily_protein_target=130,
    )
    save_profile(TEST_PROFILE_PATH, profile)
    loaded = load_profile(TEST_PROFILE_PATH)

    assert loaded == profile
    assert "no_chicken_breast" in loaded.diet_preferences


def test_load_profile_rejects_invalid_json():
    path = Path("backend/data/profile_loader_invalid.json")
    path.write_text(json.dumps({"height_cm": 10}), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_profile(path)
