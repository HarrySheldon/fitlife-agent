from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.infrastructure.postgres.runtime import initialize_database
from backend.main import create_app


def _setup_client(tmp_path, monkeypatch) -> tuple[TestClient, dict[str, str]]:
    data_dir = tmp_path / f"target-weight-{uuid4().hex}"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("LLM_ENABLED", "false")
    get_settings.cache_clear()
    initialize_database()
    client = TestClient(create_app())
    res = client.post(
        "/auth/register",
        json={"username": "targetweight", "password": "password123", "display_name": "TW"},
    )
    assert res.status_code == 200
    headers = {"Authorization": f"Bearer {res.json()['data']['access_token']}"}
    return client, headers


def test_optional_target_weight_persists_and_clears_in_profile_and_progress(tmp_path, monkeypatch):
    client, headers = _setup_client(tmp_path, monkeypatch)
    try:
        prof = client.put(
            "/api/v1/profile",
            headers=headers,
            json={
                "age": 28,
                "height_cm": 175,
                "weight_kg": 72,
                "energy_parameter": "male",
                "activity_level": "moderate",
                "effective_from": "2026-11-01T00:00:00Z",
            },
        )
        assert prof.status_code == 200

        # Omitted target_weight_kg -> None (never falls back to synthetic 68.0).
        goal_none = client.put(
            "/api/v1/goals/overall",
            headers=headers,
            json={"goal": "fat_loss", "effective_from": "2026-11-01T00:00:00Z"},
        )
        assert goal_none.status_code == 200
        assert goal_none.json()["data"]["goal"]["target_weight_kg"] is None
        overview_none = client.get("/api/v1/progress/overview", headers=headers)
        assert overview_none.status_code == 200
        assert overview_none.json()["data"]["kpis"]["target_weight_kg"] is None

        # Explicit target_weight_kg persists even for maintenance goal.
        goal_set = client.put(
            "/api/v1/goals/overall",
            headers=headers,
            json={
                "goal": "maintenance",
                "target_weight_kg": 65.5,
                "effective_from": "2026-11-02T00:00:00Z",
            },
        )
        assert goal_set.status_code == 200
        assert goal_set.json()["data"]["goal"]["target_weight_kg"] == 65.5
        setup = client.get("/api/v1/profile", headers=headers).json()["data"]
        assert setup["goal"]["target_weight_kg"] == 65.5
        overview_set = client.get("/api/v1/progress/overview", headers=headers)
        assert overview_set.json()["data"]["kpis"]["target_weight_kg"] == 65.5

        # Explicit null clears target_weight_kg cleanly.
        goal_cleared = client.put(
            "/api/v1/goals/overall",
            headers=headers,
            json={
                "goal": "maintenance",
                "target_weight_kg": None,
                "effective_from": "2026-11-03T00:00:00Z",
            },
        )
        assert goal_cleared.status_code == 200
        assert goal_cleared.json()["data"]["goal"]["target_weight_kg"] is None
        overview_cleared = client.get("/api/v1/progress/overview", headers=headers)
        assert overview_cleared.json()["data"]["kpis"]["target_weight_kg"] is None
    finally:
        client.close()
        get_settings.cache_clear()
