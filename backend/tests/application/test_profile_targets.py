from __future__ import annotations

from dataclasses import replace
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json

import pytest

from backend.application.ports.profile_target_repository import (
    GoalVersionInput,
    ProfileTargetRepositoryError,
    ProfileVersionInput,
)
from backend.application.use_cases.profile_targets import (
    ProfileTargetService,
    TargetServiceError,
)
from backend.domain.errors import ApplicationError
from backend.domain.profile_targets import DailyTargets
from backend.infrastructure.repositories.sqlite_profile_target_repository import (
    SQLiteProfileTargetRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS
from backend.infrastructure.user_lifecycle import user_lifecycle_guard
from backend.schemas import UserProfile


NOW = datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc)


class RecordingProjection:
    def __init__(self) -> None:
        self.calls = []
        self.error: Exception | None = None

    def project(self, user_id, profile, goal, target) -> None:
        self.calls.append((user_id, profile, goal, target))
        if self.error is not None:
            raise self.error


@pytest.fixture
def repository(tmp_path):
    database = SQLiteDatabase(tmp_path / "profile-targets.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    sequence = iter(f"version-{index}" for index in range(100))
    return SQLiteProfileTargetRepository(
        database,
        clock=lambda: NOW,
        id_factory=lambda: next(sequence),
    )


@pytest.fixture
def projection():
    return RecordingProjection()


@pytest.fixture
def service(repository, projection):
    return ProfileTargetService(repository, projection)


def profile(effective_from="2026-07-22T08:00:00Z", **changes):
    values = {
        "age": 30,
        "height_cm": 175,
        "weight_kg": 70,
        "energy_parameter": "male",
        "activity_level": "moderate",
        "auto_target_disabled": False,
        "safety_conditions": (),
        "effective_from": effective_from,
    }
    values.update(changes)
    return ProfileVersionInput(**values)


def goal(effective_from="2026-07-22T08:00:00Z", value="fat_loss"):
    return GoalVersionInput(goal=value, effective_from=effective_from)


def bootstrap(service):
    service.update_profile("user-a", profile())
    return service.update_goal("user-a", goal())


def test_setup_aggregate_is_incomplete_until_all_three_versions_exist(service):
    assert service.get_setup("user-a").setup_complete is False

    service.update_profile("user-a", profile())
    partial = service.get_setup("user-a")

    assert partial.profile is not None
    assert partial.goal is None
    assert partial.target is None
    assert partial.setup_complete is False


def test_profile_and_goal_updates_are_content_idempotent_and_only_return_preview(
    service, repository
):
    first_profile = service.update_profile("user-a", profile())
    repeated_profile = service.update_profile(
        "user-a", profile("2026-07-23T08:00:00Z")
    )
    goal_result = service.update_goal("user-a", goal())

    assert repeated_profile.profile == first_profile.profile
    assert goal_result.recalculation_preview is not None
    assert repository.get_latest_target("user-a") is None


def test_mutations_use_the_injected_per_user_lifecycle_scope(repository, projection):
    entered: list[str] = []

    @contextmanager
    def mutation_scope(user_id: str):
        entered.append(user_id)
        yield

    guarded_service = ProfileTargetService(
        repository,
        projection,
        mutation_scope=mutation_scope,
    )
    guarded_service.update_profile("user-a", profile())
    result = guarded_service.update_goal("user-a", goal())
    guarded_service.confirm_target(
        "user-a",
        preview=result.recalculation_preview,
        idempotency_key="4e225bd1-b589-4cdd-859f-f23c155a45f4",
        effective_from="2026-07-22T09:00:00Z",
    )

    assert entered == ["user-a", "user-a", "user-a"]


def test_deleted_user_lifecycle_blocks_new_version_writes(
    repository,
    projection,
    tmp_path,
):
    data_dir = tmp_path / "data"
    user_id = "deleted-user"
    with user_lifecycle_guard(data_dir, user_id) as lifecycle:
        lifecycle.mark_deleted()
    guarded_service = ProfileTargetService(
        repository,
        projection,
        mutation_scope=lambda selected_user: user_lifecycle_guard(
            data_dir,
            selected_user,
        ),
    )

    with pytest.raises(ApplicationError) as captured:
        guarded_service.update_profile(user_id, profile())

    assert captured.value.code == "AUTH_TOKEN_INVALID"
    assert repository.get_latest_profile(user_id) is None


def test_deterministic_preview_uses_canonical_sha256_token(service):
    result = bootstrap(service)
    preview = result.recalculation_preview

    assert preview.targets == DailyTargets(
        calories=2172,
        carbs=291,
        protein=126,
        fat=56,
        formula_version="mifflin_st_jeor_v1",
        rationale=preview.targets.rationale,
    )
    assert preview.source == "deterministic_calculation"
    assert preview.warnings == ()
    expected_payload = {
        "formula_version": "mifflin_st_jeor_v1",
        "overall_goal_version_id": "version-1",
        "profile_version_id": "version-0",
        "source": "deterministic_calculation",
        "targets": {"calories": 2172, "carbs": 291, "fat": 56, "protein": 126},
    }
    assert preview.preview_token == hashlib.sha256(
        json.dumps(
            expected_payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def test_confirmation_persists_once_then_projects_legacy_profile(
    service, repository, projection
):
    preview = bootstrap(service).recalculation_preview

    confirmed = service.confirm_target(
        "user-a",
        preview=preview,
        idempotency_key="ee53e1db-d7bf-4f25-a23c-e3fbd5e14232",
        effective_from="2026-07-22T09:00:00Z",
    )
    replay = service.confirm_target(
        "user-a",
        preview=preview,
        idempotency_key="ee53e1db-d7bf-4f25-a23c-e3fbd5e14232",
        effective_from="2026-07-22T09:00:00Z",
    )

    assert replay.target == confirmed.target
    assert len(repository.list_targets("user-a")) == 1
    assert service.get_setup("user-a").setup_complete is True
    assert projection.calls[-1][3] == confirmed.target


def test_manual_preview_requires_warning_acknowledgement(service, repository):
    bootstrap(service)
    manual = DailyTargets(calories=1200, carbs=100, protein=80, fat=30)
    preview = service.calculate_preview("user-a", manual_targets=manual)

    assert set(preview.warnings) == {
        "TARGET_BASELINE_DEVIATION",
        "TARGET_MACRO_ENERGY_MISMATCH",
    }
    with pytest.raises(TargetServiceError) as raised:
        service.confirm_target(
            "user-a",
            preview=preview,
            idempotency_key="01e70369-3728-4d50-b524-5d61d83e5f46",
            effective_from="2026-07-22T10:00:00Z",
        )
    assert raised.value.code == "TARGET_WARNING_ACKNOWLEDGEMENT_REQUIRED"
    assert repository.get_latest_target("user-a") is None

    confirmed = service.confirm_target(
        "user-a",
        preview=preview,
        idempotency_key="01e70369-3728-4d50-b524-5d61d83e5f46",
        effective_from="2026-07-22T10:00:00Z",
        acknowledge_warnings=True,
    )
    assert confirmed.target.source == "manual"
    assert set(confirmed.target.rationale["confirmed_warnings"]) == set(
        preview.warnings
    )


def test_manual_preview_normalizes_domain_validation_errors(service):
    bootstrap(service)

    with pytest.raises(TargetServiceError) as raised:
        service.calculate_preview(
            "user-a",
            manual_targets=DailyTargets(
                calories=799,
                carbs=100,
                protein=80,
                fat=30,
            ),
        )

    assert raised.value.code == "TARGET_OUT_OF_RANGE"
    assert raised.value.status_code == 422


def test_confirmation_rejects_stale_preview_after_profile_change(service, repository):
    preview = bootstrap(service).recalculation_preview
    service.update_profile(
        "user-a", profile("2026-07-23T08:00:00Z", weight_kg=68)
    )

    with pytest.raises(TargetServiceError) as raised:
        service.confirm_target(
            "user-a",
            preview=preview,
            idempotency_key="a647fe45-48d1-4499-8212-070312848e6b",
            effective_from="2026-07-23T09:00:00Z",
        )

    assert raised.value.code == "TARGET_PREVIEW_STALE"
    assert raised.value.status_code == 412
    assert repository.get_latest_target("user-a") is None


def test_idempotency_key_reuse_with_changed_request_is_rejected(service):
    preview = bootstrap(service).recalculation_preview
    key = "3c4cfd52-3f89-4d0a-b8ed-908ef40576db"
    service.confirm_target(
        "user-a",
        preview=preview,
        idempotency_key=key,
        effective_from="2026-07-22T09:00:00Z",
    )

    with pytest.raises(TargetServiceError) as raised:
        service.confirm_target(
            "user-a",
            preview=preview,
            idempotency_key=key,
            effective_from="2026-07-22T10:00:00Z",
        )
    assert raised.value.code == "IDEMPOTENCY_KEY_REUSED"
    assert raised.value.status_code == 409


def test_repository_invariant_error_maps_to_internal_server_error(
    service, repository
):
    preview = bootstrap(service).recalculation_preview

    def fail_lookup(*_args):
        raise ProfileTargetRepositoryError("IDEMPOTENCY_RESULT_NOT_FOUND")

    repository.get_confirmation = fail_lookup
    with pytest.raises(TargetServiceError) as raised:
        service.confirm_target(
            "user-a",
            preview=preview,
            idempotency_key="bdf2ba11-c268-48a7-9138-18a5f4f5cd11",
            effective_from="2026-07-22T09:00:00Z",
        )

    assert raised.value.code == "IDEMPOTENCY_RESULT_NOT_FOUND"
    assert raised.value.status_code == 500


def test_projection_failure_is_observable_and_retry_does_not_duplicate_target(
    service, repository, projection
):
    preview = bootstrap(service).recalculation_preview
    projection.error = OSError("disk unavailable")
    arguments = {
        "preview": preview,
        "idempotency_key": "d84f1c38-cc7d-4624-ac4e-c35319b250f4",
        "effective_from": "2026-07-22T09:00:00Z",
    }

    with pytest.raises(TargetServiceError) as raised:
        service.confirm_target("user-a", **arguments)
    assert raised.value.code == "TARGET_COMPATIBILITY_WRITE_FAILED"
    assert len(repository.list_targets("user-a")) == 1

    projection.error = None
    recovered = service.confirm_target("user-a", **arguments)
    assert len(repository.list_targets("user-a")) == 1
    assert projection.calls[-1][3] == recovered.target


def test_target_history_is_user_isolated(service):
    first = bootstrap(service).recalculation_preview
    service.confirm_target(
        "user-a",
        preview=first,
        idempotency_key="1df952a0-c8fb-48fc-9fc6-39f9bb79ab7c",
        effective_from="2026-07-22T09:00:00Z",
    )
    service.update_goal("user-a", goal("2026-07-23T08:00:00Z", "maintenance"))
    second = service.calculate_preview("user-a")
    latest = service.confirm_target(
        "user-a",
        preview=second,
        idempotency_key="c90fc989-622a-4145-977f-405c5df0cd1d",
        effective_from="2026-07-23T09:00:00Z",
    )

    assert service.list_target_history("user-a")[0] == latest.target
    assert service.list_target_history("user-b") == ()


def test_successful_replay_survives_profile_change_and_skips_projection(
    service, projection
):
    preview = bootstrap(service).recalculation_preview
    arguments = {
        "preview": preview,
        "idempotency_key": "30c2609f-8232-419d-88b4-cf39f88ab659",
        "effective_from": "2026-07-22T09:00:00Z",
    }
    first = service.confirm_target("user-a", **arguments)
    assert len(projection.calls) == 1

    service.update_profile(
        "user-a", profile("2026-07-23T08:00:00Z", weight_kg=68)
    )
    replay = service.confirm_target("user-a", **arguments)

    assert replay.target == first.target
    assert len(projection.calls) == 1


def test_completed_replay_returns_before_loading_or_recalculating_versions(
    service, repository
):
    preview = bootstrap(service).recalculation_preview
    arguments = {
        "preview": preview,
        "idempotency_key": "9073cf3d-642f-4496-991c-3e4f68b27e54",
        "effective_from": "2026-07-22T09:00:00Z",
    }
    first = service.confirm_target("user-a", **arguments)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("completed replay must not load or recalculate versions")

    repository.get_profile_version = unexpected
    repository.get_goal_version = unexpected
    service._deterministic_preview = unexpected

    replay = service.confirm_target("user-a", **arguments)
    assert replay.target == first.target


def test_projection_failure_retries_original_versions_after_profile_change(
    service, repository, projection
):
    preview = bootstrap(service).recalculation_preview
    original_profile_id = preview.profile_version_id
    projection.error = OSError("disk unavailable")
    arguments = {
        "preview": preview,
        "idempotency_key": "bed07eed-31ca-49c0-bb87-49379f9d7529",
        "effective_from": "2026-07-22T09:00:00Z",
    }
    with pytest.raises(TargetServiceError):
        service.confirm_target("user-a", **arguments)

    service.update_profile(
        "user-a", profile("2026-07-23T08:00:00Z", weight_kg=68)
    )
    projection.error = None
    service._deterministic_preview = lambda *_args: (_ for _ in ()).throw(
        AssertionError("pending replay must not recalculate the preview")
    )
    recovered = service.confirm_target("user-a", **arguments)
    replay = service.confirm_target("user-a", **arguments)

    assert len(repository.list_targets("user-a")) == 1
    assert projection.calls[-1][1].id == original_profile_id
    assert replay.target == recovered.target
    assert len(projection.calls) == 2


def test_pending_confirmation_retry_projects_latest_confirmed_target(
    service,
    repository,
    projection,
):
    first_preview = bootstrap(service).recalculation_preview
    first_arguments = {
        "preview": first_preview,
        "idempotency_key": "8eb72cf7-0cd3-4c30-97f4-2d90ba128658",
        "effective_from": "2026-07-22T09:00:00Z",
    }
    projection.error = OSError("disk unavailable")
    with pytest.raises(TargetServiceError):
        service.confirm_target("user-a", **first_arguments)

    second_result = service.update_goal(
        "user-a",
        goal("2026-07-23T08:00:00Z", "maintenance"),
    )
    projection.error = None
    latest = service.confirm_target(
        "user-a",
        preview=second_result.recalculation_preview,
        idempotency_key="29db9f47-8160-4918-8e63-738995afca9d",
        effective_from="2026-07-23T09:00:00Z",
    )

    service.confirm_target("user-a", **first_arguments)

    assert repository.get_latest_target("user-a") == latest.target
    assert projection.calls[-1][3] == latest.target


def test_restricted_recalculation_returns_structured_result_after_save(
    service, repository
):
    bootstrap(service)

    result = service.update_profile(
        "user-a",
        profile(
            "2026-07-23T08:00:00Z",
            auto_target_disabled=True,
        ),
    )

    assert repository.get_latest_profile("user-a") == result.profile
    assert result.recalculation_preview is None
    assert result.recalculation_restriction == "TARGET_CALCULATION_RESTRICTED"
    manual = service.calculate_preview(
        "user-a",
        manual_targets=DailyTargets(
            calories=2000,
            carbs=250,
            protein=120,
            fat=58,
        ),
    )
    assert manual.source == "manual"


def test_file_projection_updates_only_compatible_legacy_fields():
    from backend.application.use_cases.profile_targets import FileLegacyProfileProjection

    class Fitness:
        saved = None

        def update_profile_atomically(self, update, user_id):
            current = UserProfile(
                height_cm=170,
                weight_kg=65,
                age=25,
                gender="other",
                goal="maintenance",
                weekly_training_frequency=4,
                diet_preferences=["vegetarian"],
                allergies_or_restrictions=["peanut"],
                target_weight_kg=60,
                daily_calorie_target=2000,
                daily_protein_target=100,
                experience_level="experienced",
                training_preference="strength",
                target_mode="manual",
            )
            self.saved = UserProfile.model_validate(update(current).model_dump())
            return self.saved

    fitness = Fitness()
    projection = FileLegacyProfileProjection(fitness)
    repository_profile = replace(profile(), weight_kg=300, age=100)
    repository_goal = goal(value="muscle_gain")

    projection.project(
        "user-a",
        replace(
            repository_profile,
        ),
        repository_goal,
        type(
            "Target",
            (),
            {"calories": 6000, "protein": 400},
        )(),
    )

    assert fitness.saved.model_dump() == {
        "height_cm": 175.0,
        "weight_kg": 300.0,
        "age": 100,
        "gender": "other",
        "goal": "muscle_gain",
        "weekly_training_frequency": 4,
        "diet_preferences": ["vegetarian"],
        "allergies_or_restrictions": ["peanut"],
        "target_weight_kg": 60.0,
        "daily_calorie_target": 6000,
        "daily_protein_target": 400,
        "experience_level": "experienced",
        "training_preference": "strength",
        "target_mode": "manual",
    }
