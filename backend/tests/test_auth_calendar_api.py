import csv
import json
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


def build_client(data_dir: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    seed_base_data(data_dir)
    return TestClient(create_app())


def make_test_data_dir() -> Path:
    return Path(".tmp") / "pytest-auth-calendar" / uuid4().hex


def seed_base_data(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    profile = {
        "height_cm": 175,
        "weight_kg": 72,
        "age": 24,
        "gender": "male",
        "goal": "fat_loss",
        "weekly_training_frequency": 4,
        "diet_preferences": ["high_protein"],
        "allergies_or_restrictions": [],
        "target_weight_kg": 68,
        "daily_calorie_target": 2100,
        "daily_protein_target": 130,
    }
    (root / "user_profile.json").write_text(json.dumps(profile), encoding="utf-8")
    with (root / "meals.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["date", "meal", "food", "amount", "calories", "protein", "carbs", "fat"])
    with (root / "workouts.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["date", "type", "exercise", "muscle_group", "sets", "reps", "weight", "duration_min"])


def register_and_authorize(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/auth/register",
        json={
            "username": "harry",
            "email": "harry@example.com",
            "phone": "13800138000",
            "password": "password123",
            "display_name": "Harry",
        },
    )

    assert response.status_code == 200
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_register_login_and_me_return_user_session(monkeypatch):
    client = build_client(make_test_data_dir(), monkeypatch)

    registered = client.post(
        "/auth/register",
        json={
            "username": "Harry",
            "email": "Harry@Example.com",
            "phone": "13800138000",
            "password": "password123",
            "display_name": "Harry",
        },
    )
    logged_in = client.post("/auth/login", json={"identifier": "harry", "password": "password123"})

    assert registered.status_code == 200
    assert registered.json()["success"] is True
    assert registered.json()["data"]["token_type"] == "bearer"
    assert registered.json()["data"]["user"]["username"] == "harry"
    assert registered.json()["data"]["user"]["email"] == "harry@example.com"
    assert registered.json()["data"]["user"]["phone"] == "13800138000"
    assert logged_in.status_code == 200
    assert logged_in.json()["data"]["access_token"]

    token = logged_in.json()["data"]["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert me.status_code == 200
    assert me.json()["data"]["username"] == "harry"
    assert me.json()["data"]["email"] == "harry@example.com"
    assert me.json()["data"]["phone"] == "13800138000"
    assert me.json()["data"]["display_name"] == "Harry"


def test_email_and_phone_can_login_without_external_verification(monkeypatch):
    client = build_client(make_test_data_dir(), monkeypatch)
    registered = client.post(
        "/auth/register",
        json={
            "username": "fit_user",
            "email": "fit@example.com",
            "phone": "+8613800138000",
            "password": "password123",
            "display_name": "Fit User",
        },
    )

    email_login = client.post("/auth/login", json={"identifier": "FIT@example.com", "password": "password123"})
    phone_login = client.post("/auth/login", json={"identifier": "13800138000", "password": "password123"})

    assert registered.status_code == 200
    assert email_login.status_code == 200
    assert phone_login.status_code == 200
    assert email_login.json()["data"]["user"]["user_id"] == registered.json()["data"]["user"]["user_id"]
    assert phone_login.json()["data"]["user"]["user_id"] == registered.json()["data"]["user"]["user_id"]


def test_login_failure_uses_generic_account_error(monkeypatch):
    client = build_client(make_test_data_dir(), monkeypatch)

    response = client.post("/auth/login", json={"identifier": "missing-user", "password": "password123"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid account or password"


def test_calendar_records_drive_day_detail_and_dashboard_summary(monkeypatch):
    client = build_client(make_test_data_dir(), monkeypatch)
    headers = register_and_authorize(client)

    meal = client.post(
        "/calendar/meals",
        headers=headers,
        json={
            "date": "2026-07-08",
            "meal": "lunch",
            "food": "beef rice",
            "amount": "1 bowl",
            "calories": 620,
            "protein": 38,
            "carbs": 72,
            "fat": 16,
        },
    )
    workout = client.post(
        "/calendar/workouts",
        headers=headers,
        json={
            "date": "2026-07-08",
            "type": "strength",
            "exercise": "squat",
            "muscle_group": "legs",
            "sets": 4,
            "reps": 8,
            "weight": 80,
            "duration_min": 50,
        },
    )

    assert meal.status_code == 200
    assert workout.status_code == 200
    assert meal.json()["processing_mode"] == "deterministic"
    assert workout.json()["processing_mode"] == "deterministic"

    day = client.get("/calendar/day/2026-07-08", headers=headers)
    days = client.get("/calendar/days?start=2026-07-08&end=2026-07-08", headers=headers)
    dashboard = client.get("/dashboard/summary?date=2026-07-08", headers=headers)

    assert day.json()["data"]["summary"]["calories"] == 620
    assert day.json()["processing_mode"] == "deterministic"
    assert days.json()["processing_mode"] == "deterministic"
    assert dashboard.json()["processing_mode"] == "deterministic"
    assert day.json()["data"]["summary"]["training_sessions"] == 1
    assert len(day.json()["data"]["meals"]) == 1
    assert len(day.json()["data"]["workouts"]) == 1
    assert days.json()["data"][0]["protein"] == 38
    assert dashboard.json()["data"]["today_calories"] == 620
    assert dashboard.json()["data"]["weekly_training_count"] == 1


def test_agent_entry_can_append_meal_and_workout_records(monkeypatch):
    client = build_client(make_test_data_dir(), monkeypatch)
    headers = register_and_authorize(client)

    response = client.post(
        "/calendar/agent-entry",
        headers=headers,
        json={"date": "2026-07-08", "text": "午餐牛肉饭 650 kcal 蛋白质 42g，晚上跑步 30 分钟"},
    )
    day = client.get("/calendar/day/2026-07-08", headers=headers)

    assert response.status_code == 200
    assert response.json()["processing_mode"] == "deterministic"
    assert response.json()["data"]["parsed_actions"] == ["meal_record_created", "workout_record_created"]
    assert day.json()["data"]["summary"]["calories"] == 650
    assert day.json()["data"]["summary"]["protein"] == 42
    assert day.json()["data"]["summary"]["training_duration_min"] == 30
