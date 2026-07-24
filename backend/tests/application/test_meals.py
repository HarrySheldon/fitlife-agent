from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import uuid4

import pytest

from backend.application.ports.meal_repository import MealRepositoryError
from backend.application.use_cases.meals import MealService, MealServiceError


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


def test_create_draft_sets_server_controlled_thirty_day_expiry():
    repository = Mock()
    repository.create_draft.return_value = object()
    service = MealService(repository, clock=lambda: NOW)
    payload = object()

    created = service.create_draft("user-a", payload)

    assert created is repository.create_draft.return_value
    assert repository.create_draft.call_args.args == ("user-a", payload)
    assert (
        repository.create_draft.call_args.kwargs["expires_at"]
        == "2026-08-23T12:00:00Z"
    )


@pytest.mark.parametrize(
    ("code", "status_code"),
    [
        ("DRAFT_NOT_FOUND", 404),
        ("DRAFT_EXPIRED", 410),
        ("DRAFT_VERSION_CONFLICT", 409),
        ("IDEMPOTENCY_KEY_REUSED", 409),
        ("DRAFT_INCOMPLETE", 422),
    ],
)
def test_repository_errors_map_to_stable_http_status(code, status_code):
    repository = Mock()
    repository.update_draft.side_effect = MealRepositoryError(code)
    service = MealService(repository, clock=lambda: NOW)

    with pytest.raises(MealServiceError) as captured:
        service.update_draft(
            "user-a",
            "draft-1",
            expected_version=1,
            payload=object(),
        )

    assert captured.value.code == code
    assert captured.value.status_code == status_code
    assert captured.value.processing_mode == "deterministic"


def test_delete_maps_repository_error_through_service_boundary():
    repository = Mock()
    repository.delete_draft.side_effect = MealRepositoryError(
        "DRAFT_NOT_FOUND"
    )
    service = MealService(repository, clock=lambda: NOW)

    with pytest.raises(MealServiceError) as captured:
        service.delete_draft("user-a", "missing")

    assert captured.value.code == "DRAFT_NOT_FOUND"
    assert captured.value.status_code == 404


def test_confirm_requires_uuid_and_builds_stable_request_fingerprint():
    repository = Mock()
    repository.confirm.return_value = object()
    service = MealService(repository, clock=lambda: NOW)
    key = str(uuid4())

    confirmed = service.confirm_draft(
        "user-a",
        "draft-1",
        expected_version=3,
        idempotency_key=key,
    )

    assert confirmed is repository.confirm.return_value
    call = repository.confirm.call_args
    assert call.args == ("user-a", "draft-1")
    assert call.kwargs["expected_version"] == 3
    assert call.kwargs["idempotency_key"] == key
    assert len(call.kwargs["request_fingerprint"]) == 64

    with pytest.raises(MealServiceError) as invalid:
        service.confirm_draft(
            "user-a",
            "draft-1",
            expected_version=3,
            idempotency_key="not-a-uuid",
        )
    assert invalid.value.code == "INVALID_IDEMPOTENCY_KEY"
    assert invalid.value.status_code == 422
