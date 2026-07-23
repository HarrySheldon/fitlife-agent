from __future__ import annotations

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
    data_dir = Path(".tmp") / "pytest-profile-targets-api" / uuid4().hex
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client


def register(client: TestClient, username: str) -> dict:
    response = client.post(
        "/auth/register",
        json={
            "username": username,
            "password": "password123",
            "display_name": username,
        },
    )
    assert response.status_code == 200
    return response.json()["data"]


def authorization(session: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['access_token']}"}


def profile_payload(**changes) -> dict:
    payload = {
        "age": 30,
        "height_cm": 175,
        "weight_kg": 70,
        "energy_parameter": "male",
        "activity_level": "moderate",
        "auto_target_disabled": False,
        "safety_conditions": [],
        "effective_from": "2026-07-22T16:00:00+08:00",
    }
    payload.update(changes)
    return payload


def goal_payload(**changes) -> dict:
    payload = {
        "goal": "fat_loss",
        "effective_from": "2026-07-22T08:00:00Z",
    }
    payload.update(changes)
    return payload


def confirm_payload(preview: dict, **changes) -> dict:
    payload = {
        "effective_from": "2026-07-22T09:00:00Z",
        "preview": {
            "profile_version_id": preview["profile_version_id"],
            "overall_goal_version_id": preview["overall_goal_version_id"],
            "targets": preview["targets"],
            "source": preview["source"],
            "formula_version": preview["formula_version"],
            "warnings": preview["warnings"],
            "preview_token": preview["preview_token"],
        },
        "acknowledge_warnings": False,
    }
    payload.update(changes)
    return payload


def bootstrap_preview(client: TestClient, headers: dict[str, str]) -> dict:
    assert client.put(
        "/api/v1/profile",
        headers=headers,
        json=profile_payload(),
    ).status_code == 200
    response = client.put(
        "/api/v1/goals/overall",
        headers=headers,
        json=goal_payload(),
    )
    assert response.status_code == 200
    return response.json()["data"]["recalculation_preview"]


def test_authenticated_profile_target_workflow_is_explicit_and_versioned(client):
    session = register(client, "profile-target-user")
    headers = authorization(session)

    initial = client.get("/api/v1/profile", headers=headers)
    assert initial.status_code == 200
    assert initial.json()["data"] == {
        "profile": None,
        "goal": None,
        "target": None,
        "setup_complete": False,
    }

    profile = client.put(
        "/api/v1/profile",
        headers=headers,
        json=profile_payload(),
    )
    assert profile.status_code == 200
    assert profile.json()["data"]["profile"]["effective_from"] == (
        "2026-07-22T08:00:00Z"
    )
    assert profile.json()["data"]["recalculation_preview"] is None

    goal = client.put(
        "/api/v1/goals/overall",
        headers=headers,
        json=goal_payload(),
    )
    assert goal.status_code == 200
    preview = goal.json()["data"]["recalculation_preview"]
    assert preview["targets"] == {
        "calories": 2172,
        "carbs": 291,
        "protein": 126,
        "fat": 56,
    }
    assert preview["source"] == "deterministic_calculation"
    assert preview["formula_version"] == "mifflin_st_jeor_v1"

    calculated = client.post(
        "/api/v1/targets/calculate",
        headers=headers,
        json={},
    )
    assert calculated.status_code == 200
    assert calculated.json()["data"] == preview

    key = str(uuid4())
    confirmed = client.post(
        "/api/v1/targets/confirm",
        headers={
            **headers,
            "If-Match": preview["preview_token"],
            "Idempotency-Key": key,
        },
        json=confirm_payload(preview),
    )
    assert confirmed.status_code == 200
    target = confirmed.json()["data"]["target"]
    assert target["source"] == "deterministic_calculation"

    replay = client.post(
        "/api/v1/targets/confirm",
        headers={
            **headers,
            "If-Match": preview["preview_token"],
            "Idempotency-Key": key,
        },
        json=confirm_payload(preview),
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["target"] == target

    setup = client.get("/api/v1/profile", headers=headers)
    history = client.get("/api/v1/targets/history", headers=headers)
    assert setup.json()["data"]["setup_complete"] is True
    assert history.json()["data"] == [target]


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/v1/profile", None),
        ("put", "/api/v1/profile", profile_payload()),
        ("get", "/api/v1/goals", None),
        ("put", "/api/v1/goals/overall", goal_payload()),
        ("post", "/api/v1/targets/calculate", {}),
        (
            "post",
            "/api/v1/targets/confirm",
            {
                "effective_from": "2026-07-22T09:00:00Z",
                "preview": {
                    "profile_version_id": "profile",
                    "overall_goal_version_id": "goal",
                    "targets": {
                        "calories": 2000,
                        "carbs": 250,
                        "protein": 120,
                        "fat": 58,
                    },
                    "source": "manual",
                    "preview_token": "0" * 64,
                },
            },
        ),
        ("get", "/api/v1/targets/history", None),
    ],
)
def test_all_profile_target_routes_require_authentication(
    client,
    method: str,
    path: str,
    payload: dict | None,
):
    response = client.request(method.upper(), path, json=payload)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_profile_goal_and_history_reads_are_user_isolated(client):
    first = register(client, "isolated-first")
    second = register(client, "isolated-second")
    first_headers = authorization(first)
    second_headers = authorization(second)

    client.put(
        "/api/v1/profile",
        headers=first_headers,
        json=profile_payload(),
    )
    goal_response = client.put(
        "/api/v1/goals/overall",
        headers=first_headers,
        json=goal_payload(),
    )
    preview = goal_response.json()["data"]["recalculation_preview"]
    client.post(
        "/api/v1/targets/confirm",
        headers={
            **first_headers,
            "If-Match": preview["preview_token"],
            "Idempotency-Key": str(uuid4()),
        },
        json=confirm_payload(preview),
    )

    assert client.get("/api/v1/profile", headers=second_headers).json()["data"] == {
        "profile": None,
        "goal": None,
        "target": None,
        "setup_complete": False,
    }
    assert client.get("/api/v1/goals", headers=second_headers).json()["data"] == {
        "overall": None
    }
    assert (
        client.get("/api/v1/targets/history", headers=second_headers).json()[
            "data"
        ]
        == []
    )


def test_agent_target_draft_route_is_not_exposed(client):
    session = register(client, "no-agent-draft")
    response = client.post(
        "/api/v1/targets/agent-draft",
        headers=authorization(session),
        json={},
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("headers", "expected_code"),
    [
        ({"Idempotency-Key": "f530c7bd-1a0e-488d-b1fe-59800f74814a"}, "TARGET_PREVIEW_TOKEN_REQUIRED"),
        (
            {
                "If-Match": "not-a-preview-token",
                "Idempotency-Key": "f530c7bd-1a0e-488d-b1fe-59800f74814a",
            },
            "TARGET_PREVIEW_INVALID",
        ),
        ({"If-Match": "preview-token"}, "IDEMPOTENCY_KEY_REQUIRED"),
    ],
)
def test_confirmation_rejects_missing_or_invalid_preview_headers(
    client,
    headers: dict[str, str],
    expected_code: str,
):
    session = register(client, f"header-{expected_code.lower()}")
    auth_headers = authorization(session)
    preview = bootstrap_preview(client, auth_headers)
    supplied = {**auth_headers, **headers}
    if supplied.get("If-Match") == "preview-token":
        supplied["If-Match"] = preview["preview_token"]

    response = client.post(
        "/api/v1/targets/confirm",
        headers=supplied,
        json=confirm_payload(preview),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == expected_code


def test_confirmation_rejects_invalid_idempotency_uuid(client):
    session = register(client, "invalid-idempotency")
    headers = authorization(session)
    preview = bootstrap_preview(client, headers)

    response = client.post(
        "/api/v1/targets/confirm",
        headers={
            **headers,
            "If-Match": preview["preview_token"],
            "Idempotency-Key": "not-a-uuid",
        },
        json=confirm_payload(preview),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_IDEMPOTENCY_KEY"


def test_confirmation_rejects_body_and_if_match_preview_token_mismatch(client):
    session = register(client, "preview-token-mismatch")
    headers = authorization(session)
    preview = bootstrap_preview(client, headers)
    payload = confirm_payload(preview)
    payload["preview"]["preview_token"] = "f" * 64

    response = client.post(
        "/api/v1/targets/confirm",
        headers={
            **headers,
            "If-Match": preview["preview_token"],
            "Idempotency-Key": str(uuid4()),
        },
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TARGET_PREVIEW_INVALID"
    assert (
        client.get("/api/v1/targets/history", headers=headers).json()["data"]
        == []
    )


def test_confirmation_accepts_quoted_if_match_with_bare_body_preview_token(client):
    session = register(client, "quoted-if-match")
    headers = authorization(session)
    preview = bootstrap_preview(client, headers)

    response = client.post(
        "/api/v1/targets/confirm",
        headers={
            **headers,
            "If-Match": f'"{preview["preview_token"]}"',
            "Idempotency-Key": str(uuid4()),
        },
        json=confirm_payload(preview),
    )

    assert response.status_code == 200
    assert response.json()["data"]["target"]["calories"] == 2172


def test_profile_target_service_dependency_can_be_overridden(client):
    from backend.api.profile_targets import get_profile_target_service
    from backend.application.use_cases.profile_targets import (
        ProfileSetupAggregate,
    )

    session = register(client, "service-override")

    class StubService:
        user_ids: list[str] = []

        def get_setup(self, user_id: str):
            self.user_ids.append(user_id)
            return ProfileSetupAggregate(
                profile=None,
                goal=None,
                target=None,
                setup_complete=True,
            )

    service = StubService()
    client.app.dependency_overrides[get_profile_target_service] = lambda: service
    try:
        response = client.get(
            "/api/v1/profile",
            headers=authorization(session),
        )
    finally:
        client.app.dependency_overrides.pop(get_profile_target_service, None)

    assert response.status_code == 200
    assert response.json()["data"]["setup_complete"] is True
    assert service.user_ids == [session["user"]["user_id"]]


def test_stale_if_match_is_rejected_after_profile_change(client):
    session = register(client, "stale-preview")
    headers = authorization(session)
    preview = bootstrap_preview(client, headers)
    updated = client.put(
        "/api/v1/profile",
        headers=headers,
        json=profile_payload(
            weight_kg=68,
            effective_from="2026-07-23T08:00:00Z",
        ),
    )
    assert updated.status_code == 200

    response = client.post(
        "/api/v1/targets/confirm",
        headers={
            **headers,
            "If-Match": preview["preview_token"],
            "Idempotency-Key": str(uuid4()),
        },
        json=confirm_payload(preview),
    )

    assert response.status_code == 412
    assert response.json()["error"]["code"] == "TARGET_PREVIEW_STALE"
    assert (
        client.get("/api/v1/targets/history", headers=headers).json()["data"]
        == []
    )


def test_same_idempotency_key_with_changed_request_conflicts(client):
    session = register(client, "idempotency-conflict")
    headers = authorization(session)
    preview = bootstrap_preview(client, headers)
    key = str(uuid4())
    confirmation_headers = {
        **headers,
        "If-Match": preview["preview_token"],
        "Idempotency-Key": key,
    }
    first = client.post(
        "/api/v1/targets/confirm",
        headers=confirmation_headers,
        json=confirm_payload(preview),
    )
    assert first.status_code == 200

    response = client.post(
        "/api/v1/targets/confirm",
        headers=confirmation_headers,
        json=confirm_payload(
            preview,
            effective_from="2026-07-22T10:00:00Z",
        ),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert (
        len(
            client.get("/api/v1/targets/history", headers=headers).json()[
                "data"
            ]
        )
        == 1
    )


def test_exact_replay_returns_first_target_after_profile_and_goal_change(client):
    session = register(client, "replay-after-setup-change")
    headers = authorization(session)
    preview = bootstrap_preview(client, headers)
    key = str(uuid4())
    confirmation_headers = {
        **headers,
        "If-Match": preview["preview_token"],
        "Idempotency-Key": key,
    }
    payload = confirm_payload(preview)
    first = client.post(
        "/api/v1/targets/confirm",
        headers=confirmation_headers,
        json=payload,
    )
    assert first.status_code == 200

    assert client.put(
        "/api/v1/profile",
        headers=headers,
        json=profile_payload(
            weight_kg=68,
            effective_from="2026-07-23T08:00:00Z",
        ),
    ).status_code == 200
    assert client.put(
        "/api/v1/goals/overall",
        headers=headers,
        json=goal_payload(
            goal="maintenance",
            effective_from="2026-07-23T08:00:00Z",
        ),
    ).status_code == 200

    replay = client.post(
        "/api/v1/targets/confirm",
        headers=confirmation_headers,
        json=payload,
    )

    assert replay.status_code == 200
    assert replay.json()["data"]["target"] == first.json()["data"]["target"]
    assert (
        len(
            client.get("/api/v1/targets/history", headers=headers).json()[
                "data"
            ]
        )
        == 1
    )


@pytest.mark.parametrize(
    ("idempotency_key", "expected_code"),
    [
        (None, "IDEMPOTENCY_KEY_REQUIRED"),
        ("not-a-uuid", "INVALID_IDEMPOTENCY_KEY"),
    ],
)
def test_idempotency_header_is_validated_before_setup_reads(
    client,
    idempotency_key: str | None,
    expected_code: str,
):
    session = register(client, f"early-{expected_code.lower()}")
    headers = {
        **authorization(session),
        "If-Match": "0" * 64,
    }
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    payload = {
        "effective_from": "2026-07-22T09:00:00Z",
        "preview": {
            "profile_version_id": "profile-version",
            "overall_goal_version_id": "goal-version",
            "targets": {
                "calories": 2000,
                "carbs": 250,
                "protein": 120,
                "fat": 58,
            },
            "source": "manual",
            "preview_token": "f" * 64,
        },
    }

    response = client.post(
        "/api/v1/targets/confirm",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == expected_code


def test_idempotency_uuid_is_canonicalized_before_service_lookup(client):
    session = register(client, "canonical-idempotency-key")
    headers = authorization(session)
    preview = bootstrap_preview(client, headers)
    key = uuid4()
    payload = confirm_payload(preview)
    common_headers = {
        **headers,
        "If-Match": preview["preview_token"],
    }

    first = client.post(
        "/api/v1/targets/confirm",
        headers={**common_headers, "Idempotency-Key": key.hex.upper()},
        json=payload,
    )
    replay = client.post(
        "/api/v1/targets/confirm",
        headers={**common_headers, "Idempotency-Key": str(key)},
        json=payload,
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["data"]["target"] == first.json()["data"]["target"]
    assert (
        len(
            client.get("/api/v1/targets/history", headers=headers).json()[
                "data"
            ]
        )
        == 1
    )


def test_manual_warning_requires_explicit_acknowledgement(client):
    session = register(client, "manual-warning")
    headers = authorization(session)
    bootstrap_preview(client, headers)
    calculated = client.post(
        "/api/v1/targets/calculate",
        headers=headers,
        json={
            "manual_targets": {
                "calories": 1200,
                "carbs": 100,
                "protein": 80,
                "fat": 30,
            }
        },
    )
    assert calculated.status_code == 200
    preview = calculated.json()["data"]
    assert preview["requires_confirmation"] is True
    assert set(preview["warnings"]) == {
        "TARGET_BASELINE_DEVIATION",
        "TARGET_MACRO_ENERGY_MISMATCH",
    }

    key = str(uuid4())
    rejected = client.post(
        "/api/v1/targets/confirm",
        headers={
            **headers,
            "If-Match": preview["preview_token"],
            "Idempotency-Key": key,
        },
        json=confirm_payload(preview),
    )
    assert rejected.status_code == 409
    assert (
        rejected.json()["error"]["code"]
        == "TARGET_WARNING_ACKNOWLEDGEMENT_REQUIRED"
    )

    accepted_payload = confirm_payload(preview)
    accepted_payload["acknowledge_warnings"] = True
    accepted = client.post(
        "/api/v1/targets/confirm",
        headers={
            **headers,
            "If-Match": preview["preview_token"],
            "Idempotency-Key": key,
        },
        json=accepted_payload,
    )
    assert accepted.status_code == 200
    assert set(
        accepted.json()["data"]["target"]["rationale"]["confirmed_warnings"]
    ) == set(preview["warnings"])


def test_confirmation_ignores_client_computed_deterministic_values(client):
    session = register(client, "authoritative-preview")
    headers = authorization(session)
    preview = bootstrap_preview(client, headers)
    tampered = confirm_payload(preview)
    tampered["preview"]["targets"] = {
        "calories": 6000,
        "carbs": 1000,
        "protein": 400,
        "fat": 300,
    }
    tampered["preview"]["warnings"] = ["CLIENT_SUPPLIED_WARNING"]
    tampered["preview"]["formula_version"] = "client_formula"

    response = client.post(
        "/api/v1/targets/confirm",
        headers={
            **headers,
            "If-Match": preview["preview_token"],
            "Idempotency-Key": str(uuid4()),
        },
        json=tampered,
    )

    assert response.status_code == 200
    target = response.json()["data"]["target"]
    assert {
        key: target[key] for key in ("calories", "carbs", "protein", "fat")
    } == preview["targets"]
    assert target["formula_version"] == "mifflin_st_jeor_v1"
    assert target["rationale"]["warnings"] == []


def test_restricted_profile_is_saved_and_requires_manual_targets(client):
    session = register(client, "restricted-targets")
    headers = authorization(session)
    profile = client.put(
        "/api/v1/profile",
        headers=headers,
        json=profile_payload(
            auto_target_disabled=True,
            safety_conditions=["pregnancy"],
        ),
    )
    assert profile.status_code == 200
    goal = client.put(
        "/api/v1/goals/overall",
        headers=headers,
        json=goal_payload(),
    )
    assert goal.status_code == 200
    assert goal.json()["data"]["recalculation_preview"] is None
    assert (
        goal.json()["data"]["recalculation_restriction"]
        == "TARGET_CALCULATION_RESTRICTED"
    )

    automatic = client.post(
        "/api/v1/targets/calculate",
        headers=headers,
        json={},
    )
    assert automatic.status_code == 422
    assert automatic.json()["error"]["code"] == "TARGET_CALCULATION_RESTRICTED"

    manual = client.post(
        "/api/v1/targets/calculate",
        headers=headers,
        json={
            "manual_targets": {
                "calories": 2000,
                "carbs": 250,
                "protein": 120,
                "fat": 58,
            }
        },
    )
    assert manual.status_code == 200
    assert manual.json()["data"]["source"] == "manual"


def test_request_validation_has_stable_envelope_and_forbids_extra_fields(client):
    session = register(client, "validation-envelope")
    response = client.put(
        "/api/v1/profile",
        headers=authorization(session),
        json={**profile_payload(), "user_id": "another-user"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_user_cannot_confirm_another_users_preview(client):
    first = register(client, "preview-owner")
    second = register(client, "preview-attacker")
    first_headers = authorization(first)
    second_headers = authorization(second)
    first_preview = bootstrap_preview(client, first_headers)
    bootstrap_preview(client, second_headers)

    response = client.post(
        "/api/v1/targets/confirm",
        headers={
            **second_headers,
            "If-Match": first_preview["preview_token"],
            "Idempotency-Key": str(uuid4()),
        },
        json=confirm_payload(first_preview),
    )

    assert response.status_code == 412
    assert response.json()["error"]["code"] == "TARGET_PREVIEW_STALE"
    assert (
        client.get("/api/v1/targets/history", headers=second_headers).json()[
            "data"
        ]
        == []
    )


def test_calculation_requires_both_profile_and_overall_goal(client):
    session = register(client, "incomplete-setup")
    response = client.post(
        "/api/v1/targets/calculate",
        headers=authorization(session),
        json={},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PROFILE_TARGET_SETUP_INCOMPLETE"


def test_effective_from_requires_timezone_awareness(client):
    session = register(client, "timezone-required")
    response = client.put(
        "/api/v1/profile",
        headers=authorization(session),
        json=profile_payload(effective_from="2026-07-22T08:00:00"),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
