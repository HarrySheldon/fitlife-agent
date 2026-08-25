import csv

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import create_app


@pytest.fixture(autouse=True)
def reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_anonymous_legacy_agent_entry_returns_draft_without_persisting(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    for filename, header in (
        ("meals.csv", ["date", "meal", "food", "amount", "calories", "protein", "carbs", "fat"]),
        ("workouts.csv", ["date", "type", "exercise", "muscle_group", "sets", "reps", "weight", "duration_min"]),
    ):
        with (tmp_path / filename).open("w", newline="", encoding="utf-8") as file:
            csv.writer(file).writerow(header)

    with TestClient(create_app()) as client:
        response = client.post(
            "/calendar/agent-entry",
            json={"date": "2026-07-08", "text": "lunch 650 kcal protein 42g, run 30 minutes"},
        )
        day = client.get("/calendar/day/2026-07-08")

    assert response.status_code == 200
    assert response.json()["data"]["parsed_actions"] == [
        "meal_record_proposed",
        "workout_record_proposed",
    ]
    assert day.json()["data"]["meals"] == []
    assert day.json()["data"]["workouts"] == []
