from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from backend.application.ports.workout_repository import (
    WorkoutDraftInput,
    WorkoutRepositoryError,
)
from backend.application.use_cases.workouts import (
    WorkoutService,
    WorkoutServiceError,
)


NOW = datetime(2026, 7, 25, 12, tzinfo=timezone.utc)
EMPTY = WorkoutDraftInput(
    log_date="2026-07-25",
    title="Session",
    started_at=None,
    duration_min=None,
    intensity=None,
    entry_method="form",
    strength_exercises=(),
    cardio_items=(),
)


def test_create_draft_sets_thirty_day_expiry():
    repository = Mock()
    service = WorkoutService(repository, clock=lambda: NOW)

    service.create_draft("user-a", EMPTY)

    assert repository.create_draft.call_args.kwargs["expires_at"] == (
        "2026-08-24T12:00:00Z"
    )


def test_confirm_requires_uuid_and_scopes_fingerprint_to_user():
    repository = Mock()
    repository.confirm.return_value = Mock()
    service = WorkoutService(repository, clock=lambda: NOW)
    key = "5f6c8708-678c-45a6-a95e-7fb7f0dbbb9d"

    service.confirm_draft(
        "user-a",
        "draft-a",
        expected_version=2,
        idempotency_key=key,
    )

    call = repository.confirm.call_args
    assert call.kwargs["idempotency_key"] == key
    assert len(call.kwargs["request_fingerprint"]) == 64
    with pytest.raises(WorkoutServiceError) as raised:
        service.confirm_draft(
            "user-a",
            "draft-a",
            expected_version=2,
            idempotency_key="not-a-uuid",
        )
    assert raised.value.code == "INVALID_IDEMPOTENCY_KEY"


def test_repository_conflict_maps_to_public_409():
    repository = Mock()
    repository.update_draft.side_effect = WorkoutRepositoryError(
        "DRAFT_VERSION_CONFLICT"
    )
    service = WorkoutService(repository, clock=lambda: NOW)

    with pytest.raises(WorkoutServiceError) as raised:
        service.update_draft(
            "user-a",
            "draft-a",
            expected_version=1,
            payload=EMPTY,
        )

    assert raised.value.status_code == 409
