import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import create_app


@pytest.fixture(autouse=True)
def reset_settings_cache():
    yield
    get_settings.cache_clear()


def build_client(monkeypatch) -> TestClient:
    root = Path(".tmp") / "pytest-timezone-boundaries" / uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    (root / "user_profile.json").write_text(
        json.dumps(
            {
                "height_cm": 175,
                "weight_kg": 72,
                "age": 24,
                "gender": "male",
                "goal": "maintenance",
                "weekly_training_frequency": 3,
                "diet_preferences": [],
                "allergies_or_restrictions": [],
                "target_weight_kg": 72,
                "daily_calorie_target": 2200,
                "daily_protein_target": 130,
            }
        ),
        encoding="utf-8",
    )
    for name, columns in {
        "meals.csv": ["date", "meal", "food", "amount", "calories", "protein", "carbs", "fat"],
        "workouts.csv": ["date", "type", "exercise", "muscle_group", "sets", "reps", "weight", "duration_min"],
    }.items():
        with (root / name).open("w", newline="", encoding="utf-8") as file:
            csv.writer(file).writerow(columns)
    monkeypatch.setenv("DATA_DIR", str(root))
    monkeypatch.setattr(
        "backend.domain.account_clock.utc_now",
        lambda: datetime(2026, 7, 13, 0, 30, tzinfo=timezone.utc),
    )
    get_settings.cache_clear()
    return TestClient(create_app())


def register(client: TestClient, username: str, timezone_name: str) -> dict[str, str]:
    response = client.post(
        "/auth/register",
        json={"username": username, "password": "password123", "display_name": username},
    )
    headers = {"Authorization": f"Bearer {response.json()['data']['access_token']}"}
    saved = client.patch("/settings/preferences", headers=headers, json={"timezone": timezone_name})
    assert saved.status_code == 200
    return headers


def test_implicit_today_dashboard_and_report_use_account_timezone(monkeypatch):
    client = build_client(monkeypatch)
    shanghai = register(client, "timezone-shanghai", "Asia/Shanghai")
    los_angeles = register(client, "timezone-la", "America/Los_Angeles")

    shanghai_today = client.get("/today", headers=shanghai)
    la_today = client.get("/today", headers=los_angeles)
    shanghai_dashboard = client.get("/dashboard/summary", headers=shanghai)
    la_dashboard = client.get("/dashboard/summary", headers=los_angeles)
    shanghai_report = client.post("/report/weekly", headers=shanghai)
    la_report = client.post("/report/weekly", headers=los_angeles)

    assert shanghai_today.json()["data"]["date"] == "2026-07-13"
    assert la_today.json()["data"]["date"] == "2026-07-12"
    assert shanghai_dashboard.json()["data"]["summary_date"] == "2026-07-13"
    assert la_dashboard.json()["data"]["summary_date"] == "2026-07-12"
    assert shanghai_report.json()["data"]["period"] == {"start": "2026-07-13", "end": "2026-07-19"}
    assert la_report.json()["data"]["period"] == {"start": "2026-07-06", "end": "2026-07-12"}


def test_explicit_dates_are_not_reinterpreted_by_timezone(monkeypatch):
    client = build_client(monkeypatch)
    headers = register(client, "timezone-explicit", "America/Los_Angeles")

    today = client.get("/today?date=2026-07-08", headers=headers)
    dashboard = client.get("/dashboard/summary?date=2026-07-08", headers=headers)

    assert today.json()["data"]["date"] == "2026-07-08"
    assert dashboard.json()["data"]["summary_date"] == "2026-07-08"

