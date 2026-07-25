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
    data_dir = Path(".tmp") / "pytest-workout-api" / uuid4().hex
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
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _profile(client: TestClient, headers: dict[str, str]) -> None:
    response = client.put(
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
    assert response.status_code == 200


def _payload(squat_id: str, running_id: str, title: str = "Mixed") -> dict:
    return {
        "log_date": "2026-07-25",
        "title": title,
        "duration_min": 45,
        "intensity": "medium",
        "entry_method": "form",
        "strength_exercises": [
            {
                "catalog_exercise_id": squat_id,
                "sets": [
                    {
                        "set_number": index,
                        "reps": 8,
                        "load_kg": 60,
                        "bodyweight": False,
                    }
                    for index in range(1, 4)
                ],
            }
        ],
        "cardio_items": [
            {
                "catalog_exercise_id": running_id,
                "duration_min": 20,
                "device_calories": None,
            }
        ],
    }


def test_catalog_custom_ownership_and_workout_draft_contract(client):
    owner = _register(client, "workout-owner")
    other = _register(client, "workout-other")
    _profile(client, owner)
    squat = client.get(
        "/api/v1/catalog/exercises/search",
        params={"q": "squat"},
        headers=owner,
    ).json()["data"][0]
    running = client.get(
        "/api/v1/catalog/exercises/search",
        params={"q": "running"},
        headers=owner,
    ).json()["data"][0]
    custom = client.post(
        "/api/v1/catalog/exercises/custom",
        headers=owner,
        json={
            "name": "Owner split squat",
            "exercise_type": "strength",
            "primary_muscle": "quadriceps",
            "secondary_muscles": ["glutes"],
            "met": None,
            "aliases": ["owner-private-movement"],
        },
    )
    assert custom.status_code == 200
    assert client.get(
        "/api/v1/catalog/exercises/search",
        params={"q": "owner-private-movement"},
        headers=other,
    ).json()["data"] == []

    created = client.post(
        "/api/v1/workout-drafts",
        headers=owner,
        json=_payload(squat["id"], running["id"]),
    )
    assert created.status_code == 200
    draft = created.json()["data"]
    assert draft["version"] == 1
    assert draft["payload"]["weight_kg_snapshot"] == 70
    assert draft["payload"]["estimated_calories"] == 515.7
    assert client.get(
        f"/api/v1/workout-drafts/{draft['id']}",
        headers=other,
    ).status_code == 404

    updated = client.patch(
        f"/api/v1/workout-drafts/{draft['id']}",
        headers={**owner, "If-Match": "1"},
        json=_payload(squat["id"], running["id"], title="Updated"),
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["version"] == 2
    stale = client.patch(
        f"/api/v1/workout-drafts/{draft['id']}",
        headers={**owner, "If-Match": "1"},
        json=_payload(squat["id"], running["id"], title="Stale"),
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == (
        "WORKOUT_DRAFT_VERSION_CONFLICT"
    )

    key = str(uuid4())
    confirmed = client.post(
        f"/api/v1/workout-drafts/{draft['id']}/confirm",
        headers={
            **owner,
            "If-Match": "2",
            "Idempotency-Key": key,
        },
    )
    assert confirmed.status_code == 200
    session = confirmed.json()["data"]
    assert len(session["strength_exercises"][0]["sets"]) == 3
    assert len(session["cardio_items"]) == 1
    replay = client.post(
        f"/api/v1/workout-drafts/{draft['id']}/confirm",
        headers={
            **owner,
            "If-Match": "2",
            "Idempotency-Key": key,
        },
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["id"] == session["id"]
    assert replay.json()["data"]["replayed"] is True


def test_workout_owner_headers_and_idempotency_contract(client):
    owner = _register(client, "workout-contract-owner")
    other = _register(client, "workout-contract-other")
    _profile(client, owner)
    squat = client.get(
        "/api/v1/catalog/exercises/search",
        params={"q": "squat"},
        headers=owner,
    ).json()["data"][0]
    running = client.get(
        "/api/v1/catalog/exercises/search",
        params={"q": "running"},
        headers=owner,
    ).json()["data"][0]
    created = client.post(
        "/api/v1/workout-drafts",
        headers=owner,
        json=_payload(squat["id"], running["id"]),
    ).json()["data"]
    path = f"/api/v1/workout-drafts/{created['id']}"

    for method, suffix, headers in (
        ("patch", "", {**other, "If-Match": "1"}),
        ("delete", "", other),
        (
            "post",
            "/confirm",
            {
                **other,
                "If-Match": "1",
                "Idempotency-Key": str(uuid4()),
            },
        ),
    ):
        response = client.request(
            method,
            f"{path}{suffix}",
            headers=headers,
            json=_payload(squat["id"], running["id"])
            if method == "patch"
            else None,
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == (
            "WORKOUT_DRAFT_NOT_FOUND"
        )

    missing_version = client.patch(
        path,
        headers=owner,
        json=_payload(squat["id"], running["id"]),
    )
    invalid_version = client.patch(
        path,
        headers={**owner, "If-Match": "0"},
        json=_payload(squat["id"], running["id"]),
    )
    missing_key = client.post(
        f"{path}/confirm",
        headers={**owner, "If-Match": "1"},
    )
    invalid_key = client.post(
        f"{path}/confirm",
        headers={
            **owner,
            "If-Match": "1",
            "Idempotency-Key": "not-a-uuid",
        },
    )
    assert missing_version.json()["error"]["code"] == (
        "WORKOUT_DRAFT_VERSION_REQUIRED"
    )
    assert invalid_version.json()["error"]["code"] == (
        "WORKOUT_DRAFT_VERSION_INVALID"
    )
    assert missing_key.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    assert invalid_key.json()["error"]["code"] == "INVALID_IDEMPOTENCY_KEY"
    assert {
        missing_version.status_code,
        invalid_version.status_code,
        missing_key.status_code,
        invalid_key.status_code,
    } == {422}

    key = str(uuid4())
    first = client.post(
        f"{path}/confirm",
        headers={
            **owner,
            "If-Match": "1",
            "Idempotency-Key": key,
        },
    )
    assert first.status_code == 200
    second_draft = client.post(
        "/api/v1/workout-drafts",
        headers=owner,
        json=_payload(squat["id"], running["id"], title="Second"),
    ).json()["data"]
    reused = client.post(
        f"/api/v1/workout-drafts/{second_draft['id']}/confirm",
        headers={
            **owner,
            "If-Match": "1",
            "Idempotency-Key": key,
        },
    )
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_exercise_favorites_are_authenticated_and_owner_scoped(client):
    owner = _register(client, "favorite-owner")
    other = _register(client, "favorite-other")
    custom = client.post(
        "/api/v1/catalog/exercises/custom",
        headers=owner,
        json={
            "name": "Private favorite",
            "exercise_type": "strength",
            "primary_muscle": "back",
        },
    ).json()["data"]

    added = client.put(
        f"/api/v1/catalog/exercises/{custom['id']}/favorite",
        headers=owner,
    )
    hidden = client.put(
        f"/api/v1/catalog/exercises/{custom['id']}/favorite",
        headers=other,
    )
    removed = client.delete(
        f"/api/v1/catalog/exercises/{custom['id']}/favorite",
        headers=owner,
    )
    assert added.status_code == 200
    assert added.json()["data"] == {"favorite": True}
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "EXERCISE_NOT_VISIBLE"
    assert removed.status_code == 200
    assert removed.json()["data"] == {"favorite": False}


def test_workout_validation_errors_are_localized(client):
    headers = _register(client, "workout-localized")
    _profile(client, headers)
    changed = client.patch(
        "/settings/preferences",
        headers=headers,
        json={"language": "zh-CN"},
    )
    assert changed.status_code == 200
    squat = client.get(
        "/api/v1/catalog/exercises/search",
        params={"q": "squat"},
        headers=headers,
    ).json()["data"][0]
    response = client.post(
        "/api/v1/workout-drafts",
        headers=headers,
        json={
            "log_date": "2026-07-25",
            "title": "缺少强度",
            "duration_min": 30,
            "strength_exercises": [
                {
                    "catalog_exercise_id": squat["id"],
                    "sets": [
                        {
                            "set_number": 1,
                            "reps": 8,
                            "load_kg": 60,
                            "bodyweight": False,
                        }
                    ],
                }
            ],
            "cardio_items": [],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "WORKOUT_INTENSITY_REQUIRED",
        "message": "填写训练时长时请选择训练强度。",
    }


def test_workout_openapi_exposes_response_contracts(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    paths = client.get("/openapi.json").json()["paths"]

    assert "WorkoutDraftResponse" in schemas
    assert "ConfirmedWorkoutResponse" in schemas
    assert "ExerciseCatalogItemResponse" in schemas
    assert (
        "ApiResponse_WorkoutDraftResponse_"
        in paths["/api/v1/workout-drafts"]["post"]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]["$ref"]
    )


def test_custom_exercise_rejects_invalid_secondary_muscle(client):
    headers = _register(client, "workout-muscle-validation")
    response = client.post(
        "/api/v1/catalog/exercises/custom",
        headers=headers,
        json={
            "name": "Invalid muscle",
            "exercise_type": "strength",
            "primary_muscle": "back",
            "secondary_muscles": [""],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/catalog/exercises/search"),
        ("post", "/api/v1/catalog/exercises/custom"),
        ("put", "/api/v1/catalog/exercises/missing/favorite"),
        ("delete", "/api/v1/catalog/exercises/missing/favorite"),
        ("post", "/api/v1/workout-drafts"),
        ("get", "/api/v1/workout-drafts/missing"),
        ("patch", "/api/v1/workout-drafts/missing"),
        ("delete", "/api/v1/workout-drafts/missing"),
        ("post", "/api/v1/workout-drafts/missing/confirm"),
    ],
)
def test_workout_routes_require_authentication(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
