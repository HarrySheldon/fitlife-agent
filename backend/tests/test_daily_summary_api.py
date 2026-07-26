import csv
from datetime import datetime, timezone
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


@pytest.fixture
def client(monkeypatch):
    data_dir = Path(".tmp") / "pytest-daily-summary-api" / uuid4().hex
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client


def _register(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/auth/register",
        json={
            "username": username,
            "password": "password123",
            "display_name": username,
        },
    )
    assert response.status_code == 200
    return {
        "Authorization": (
            f"Bearer {response.json()['data']['access_token']}"
        )
    }


def _confirm_meal(
    client: TestClient,
    headers: dict[str, str],
    *,
    log_date: str = "2026-07-25",
    name: str = "Lunch",
) -> dict:
    created = client.post(
        "/api/v1/meal-drafts",
        headers=headers,
        json={
            "log_date": log_date,
            "name": name,
            "meal_type": "lunch",
            "entry_method": "form",
            "items": [
                {
                    "amount": 150,
                    "unit": "g",
                    "custom_food": {
                        "name": "Tofu",
                        "basis_type": "per_100g",
                        "basis_amount": 100,
                        "unit": "g",
                        "calories": 80,
                        "carbs": 2,
                        "protein": 8,
                        "fat": 4,
                    },
                }
            ],
        },
    )
    assert created.status_code == 200
    draft = created.json()["data"]
    confirmed = client.post(
        f"/api/v1/meal-drafts/{draft['id']}/confirm",
        headers={
            **headers,
            "If-Match": str(draft["version"]),
            "Idempotency-Key": str(uuid4()),
        },
    )
    assert confirmed.status_code == 200
    return confirmed.json()["data"]


def _confirm_workout(
    client: TestClient,
    headers: dict[str, str],
    *,
    log_date: str = "2026-07-25",
) -> dict:
    setup = client.get("/api/v1/profile", headers=headers)
    assert setup.status_code == 200
    if setup.json()["data"]["profile"] is None:
        profile = client.put(
            "/api/v1/profile",
            headers=headers,
            json={
                "age": 30,
                "height_cm": 175,
                "weight_kg": 70,
                "energy_parameter": "neutral",
                "activity_level": "moderate",
                "auto_target_disabled": False,
                "safety_conditions": [],
                "effective_from": "2026-01-01T00:00:00Z",
            },
        )
        assert profile.status_code == 200
    created = client.post(
        "/api/v1/workout-drafts",
        headers=headers,
        json={
            "log_date": log_date,
            "title": "Mixed session",
            "duration_min": 45,
            "intensity": "medium",
            "entry_method": "form",
            "strength_exercises": [
                {
                    "custom_exercise": {
                        "name": "Split squat",
                        "exercise_type": "strength",
                        "primary_muscle": "quadriceps",
                    },
                    "sets": [
                        {
                            "set_number": 1,
                            "reps": 8,
                            "load_kg": 30,
                            "bodyweight": False,
                        },
                        {
                            "set_number": 2,
                            "reps": 8,
                            "load_kg": 30,
                            "bodyweight": False,
                        },
                    ],
                }
            ],
            "cardio_items": [
                {
                    "custom_exercise": {
                        "name": "Running",
                        "exercise_type": "cardio",
                        "primary_muscle": "cardiovascular",
                        "met": 8,
                    },
                    "duration_min": 20,
                    "device_calories": 200,
                }
            ],
        },
    )
    assert created.status_code == 200
    draft = created.json()["data"]
    confirmed = client.post(
        f"/api/v1/workout-drafts/{draft['id']}/confirm",
        headers={
            **headers,
            "If-Match": str(draft["version"]),
            "Idempotency-Key": str(uuid4()),
        },
    )
    assert confirmed.status_code == 200
    return confirmed.json()["data"]


def test_planned_meal_count_is_owner_scoped_and_validated(client):
    owner = _register(client, "daily-plan-owner")
    other = _register(client, "daily-plan-other")

    updated = client.patch(
        "/api/v1/daily-logs/2026-07-25",
        headers=owner,
        json={"planned_meal_count": 5},
    )

    assert updated.status_code == 200
    assert updated.json()["data"]["planned_meal_count"] == 5
    assert client.get(
        "/today?date=2026-07-25",
        headers=other,
    ).json()["data"]["planned_meal_count"] == 3
    assert client.patch(
        "/api/v1/daily-logs/2026-07-25",
        headers=owner,
        json={"planned_meal_count": 0},
    ).status_code == 422
    assert client.patch(
        "/api/v1/daily-logs/2026-07-25",
        json={"planned_meal_count": 4},
    ).status_code == 401


def test_confirming_extra_meals_persists_the_higher_planned_count(client):
    headers = _register(client, "daily-plan-grow")

    for index in range(4):
        _confirm_meal(client, headers, name=f"Meal {index + 1}")

    data = client.get(
        "/today?date=2026-07-25",
        headers=headers,
    ).json()["data"]
    assert data["recorded_meal_count"] == 4
    assert data["planned_meal_count"] == 4


def _setup_target_prerequisites(
    client: TestClient,
    headers: dict[str, str],
) -> None:
    profile = client.put(
        "/api/v1/profile",
        headers=headers,
        json={
            "age": 30,
            "height_cm": 175,
            "weight_kg": 70,
            "energy_parameter": "neutral",
            "activity_level": "moderate",
            "auto_target_disabled": False,
            "safety_conditions": [],
            "effective_from": "2026-01-01T00:00:00Z",
        },
    )
    goal = client.put(
        "/api/v1/goals/overall",
        headers=headers,
        json={
            "goal": "maintenance",
            "effective_from": "2026-01-01T00:00:00Z",
        },
    )
    assert profile.status_code == 200
    assert goal.status_code == 200


def _confirm_target(
    client: TestClient,
    headers: dict[str, str],
    *,
    effective_from: str,
    calories: int,
    carbs: int,
    protein: int,
    fat: int,
) -> dict:
    calculated = client.post(
        "/api/v1/targets/calculate",
        headers=headers,
        json={
            "manual_targets": {
                "calories": calories,
                "carbs": carbs,
                "protein": protein,
                "fat": fat,
            }
        },
    )
    assert calculated.status_code == 200
    preview = calculated.json()["data"]
    confirmed = client.post(
        "/api/v1/targets/confirm",
        headers={
            **headers,
            "If-Match": preview["preview_token"],
            "Idempotency-Key": str(uuid4()),
        },
        json={
            "effective_from": effective_from,
            "preview": preview,
            "acknowledge_warnings": True,
        },
    )
    assert confirmed.status_code == 200
    return confirmed.json()["data"]["target"]


def test_authenticated_empty_day_uses_sqlite_summary(client):
    headers = _register(client, "daily-empty")

    response = client.get("/today?date=2026-07-25", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"] == {
        "date": "2026-07-25",
        "target": None,
        "consumed": {
            "calories": 0,
            "carbs": 0,
            "protein": 0,
            "fat": 0,
        },
        "planned_meal_count": 3,
        "recorded_meal_count": 0,
        "coach_actions": [
            "explain_today",
            "suggest_next_meal",
        ],
    }


def test_authenticated_meal_only_day_returns_confirmed_meal_summary(client):
    headers = _register(client, "daily-meal")
    meal = _confirm_meal(client, headers)

    response = client.get("/today?date=2026-07-25", headers=headers)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["consumed"] == {
        "calories": 120,
        "carbs": 3,
        "protein": 12,
        "fat": 6,
    }
    assert data["planned_meal_count"] == 3
    assert data["recorded_meal_count"] == 1
    assert data["meals"] == [
        {
            "id": meal["id"],
            "name": "Lunch",
            "meal_type": "lunch",
            "position": 1,
            "item_count": 1,
            "nutrition": {
                "calories": 120,
                "carbs": 3,
                "protein": 12,
                "fat": 6,
            },
        }
    ]
    assert "workouts" not in data


def test_authenticated_workout_only_day_keeps_nutrition_separate(client):
    headers = _register(client, "daily-workout")
    workout = _confirm_workout(client, headers)

    response = client.get("/today?date=2026-07-25", headers=headers)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["consumed"] == {
        "calories": 0,
        "carbs": 0,
        "protein": 0,
        "fat": 0,
    }
    assert data["planned_meal_count"] == 3
    assert data["recorded_meal_count"] == 0
    assert "meals" not in data
    assert data["workouts"] == [
        {
            "id": workout["id"],
            "title": "Mixed session",
            "started_at": None,
            "duration_min": 45,
            "intensity": "medium",
            "calories": workout["estimated_calories"],
            "contains_estimates": True,
            "strength_exercise_count": 1,
            "strength_set_count": 2,
            "cardio_item_count": 1,
        }
    ]


def test_authenticated_mixed_day_returns_meals_and_workouts(client):
    headers = _register(client, "daily-mixed")
    _confirm_meal(client, headers)
    _confirm_workout(client, headers)

    response = client.get("/today?date=2026-07-25", headers=headers)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["consumed"]["calories"] == 120
    assert data["recorded_meal_count"] == 1
    assert len(data["meals"]) == 1
    assert len(data["workouts"]) == 1
    assert data["workouts"][0]["calories"] == 475.6


def test_daily_summary_selects_target_effective_for_local_date(client):
    headers = _register(client, "daily-target-history")
    changed = client.patch(
        "/settings/preferences",
        headers=headers,
        json={"timezone": "Asia/Shanghai"},
    )
    assert changed.status_code == 200
    _setup_target_prerequisites(client, headers)
    earlier = _confirm_target(
        client,
        headers,
        effective_from="2026-07-24T15:59:00Z",
        calories=2000,
        carbs=245,
        protein=120,
        fat=60,
    )
    later = _confirm_target(
        client,
        headers,
        effective_from="2026-07-24T16:00:00Z",
        calories=2400,
        carbs=300,
        protein=150,
        fat=67,
    )

    july_24 = client.get("/today?date=2026-07-24", headers=headers)
    july_25 = client.get("/today?date=2026-07-25", headers=headers)

    assert july_24.status_code == 200
    assert july_25.status_code == 200
    assert july_24.json()["data"]["target"] == {
        "id": earlier["id"],
        "calories": 2000,
        "carbs": 245,
        "protein": 120,
        "fat": 60,
        "source": "manual",
        "effective_from": "2026-07-24T15:59:00Z",
    }
    assert july_25.json()["data"]["target"] == {
        "id": later["id"],
        "calories": 2400,
        "carbs": 300,
        "protein": 150,
        "fat": 67,
        "source": "manual",
        "effective_from": "2026-07-24T16:00:00Z",
    }


def test_confirmed_daily_log_keeps_its_target_snapshot(client):
    headers = _register(client, "daily-target-snapshot")
    changed = client.patch(
        "/settings/preferences",
        headers=headers,
        json={"timezone": "Asia/Shanghai"},
    )
    assert changed.status_code == 200
    _setup_target_prerequisites(client, headers)
    original = _confirm_target(
        client,
        headers,
        effective_from="2026-07-24T16:00:00Z",
        calories=2000,
        carbs=245,
        protein=120,
        fat=60,
    )
    _confirm_meal(client, headers)
    _confirm_target(
        client,
        headers,
        effective_from="2026-07-25T00:00:00Z",
        calories=2400,
        carbs=300,
        protein=150,
        fat=67,
    )

    response = client.get("/today?date=2026-07-25", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"]["target"]["id"] == original["id"]
    assert response.json()["data"]["target"]["calories"] == 2000


def test_daily_summary_isolates_all_records_by_owner(client):
    owner = _register(client, "daily-owner")
    other = _register(client, "daily-other")
    _setup_target_prerequisites(client, owner)
    _confirm_target(
        client,
        owner,
        effective_from="2026-07-01T00:00:00Z",
        calories=2200,
        carbs=275,
        protein=140,
        fat=60,
    )
    _confirm_meal(client, owner)
    _confirm_workout(client, owner)

    response = client.get("/today?date=2026-07-25", headers=other)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["target"] is None
    assert data["consumed"] == {
        "calories": 0,
        "carbs": 0,
        "protein": 0,
        "fat": 0,
    }
    assert data["recorded_meal_count"] == 0
    assert "meals" not in data
    assert "workouts" not in data


def test_daily_summary_uses_account_timezone_only_for_default_date(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        "backend.domain.account_clock.utc_now",
        lambda: datetime(2026, 7, 25, 0, 30, tzinfo=timezone.utc),
    )
    shanghai = _register(client, "daily-date-shanghai")
    los_angeles = _register(client, "daily-date-la")
    for headers, timezone_name in (
        (shanghai, "Asia/Shanghai"),
        (los_angeles, "America/Los_Angeles"),
    ):
        changed = client.patch(
            "/settings/preferences",
            headers=headers,
            json={"timezone": timezone_name},
        )
        assert changed.status_code == 200

    shanghai_default = client.get("/today", headers=shanghai)
    los_angeles_default = client.get("/today", headers=los_angeles)
    los_angeles_explicit = client.get(
        "/today?date=2026-07-23",
        headers=los_angeles,
    )

    assert shanghai_default.json()["data"]["date"] == "2026-07-25"
    assert los_angeles_default.json()["data"]["date"] == "2026-07-24"
    assert los_angeles_explicit.json()["data"]["date"] == "2026-07-23"


@pytest.mark.parametrize("value", ["2026-02-30", "2026-7-25", "July-25"])
def test_today_rejects_non_iso_or_impossible_explicit_dates(client, value):
    headers = _register(client, f"daily-invalid-{uuid4().hex[:8]}")

    response = client.get("/today", params={"date": value}, headers=headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_unauthenticated_today_keeps_legacy_demo_contract(client):
    data_dir = get_settings().data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "user_profile.json").write_text(
        json.dumps(
            {
                "height_cm": 175,
                "weight_kg": 70,
                "age": 30,
                "gender": "other",
                "goal": "maintenance",
                "weekly_training_frequency": 0,
                "diet_preferences": [],
                "allergies_or_restrictions": [],
                "target_weight_kg": 70,
                "daily_calorie_target": 2200,
                "daily_protein_target": 130,
            }
        ),
        encoding="utf-8",
    )
    for name, columns in {
        "meals.csv": [
            "date",
            "meal",
            "food",
            "amount",
            "calories",
            "protein",
            "carbs",
            "fat",
        ],
        "workouts.csv": [
            "date",
            "type",
            "exercise",
            "muscle_group",
            "sets",
            "reps",
            "weight",
            "duration_min",
        ],
    }.items():
        with (data_dir / name).open("w", newline="", encoding="utf-8") as file:
            csv.writer(file).writerow(columns)
    response = client.get("/today?date=2026-07-25")

    assert response.status_code == 200
    data = response.json()["data"]
    assert set(data) == {
        "date",
        "summary",
        "meals",
        "workouts",
        "targets",
        "coach_actions",
    }
    assert data["date"] == "2026-07-25"
    assert "consumed" not in data
    assert "planned_meal_count" not in data
