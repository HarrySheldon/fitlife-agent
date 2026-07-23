from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable
from uuid import UUID

from backend.application.ports.fitness_repository import FitnessRepository
from backend.application.ports.profile_target_repository import (
    GoalVersion,
    GoalVersionInput,
    ProfileTargetRepository,
    ProfileTargetRepositoryError,
    ProfileVersion,
    ProfileVersionInput,
    TargetSource,
    TargetVersion,
    TargetVersionInput,
)
from backend.domain.profile_targets import (
    DailyTargets,
    ProfileInput,
    TargetDomainError,
    calculate_daily_targets,
    evaluate_manual_targets,
)
from backend.domain.errors import ApplicationError


@dataclass(frozen=True)
class TargetPreview:
    profile_version_id: str
    overall_goal_version_id: str
    targets: DailyTargets
    source: TargetSource
    warnings: tuple[str, ...]
    requires_confirmation: bool
    preview_token: str


@dataclass(frozen=True)
class ProfileSetupAggregate:
    profile: ProfileVersion | None
    goal: GoalVersion | None
    target: TargetVersion | None
    setup_complete: bool


@dataclass(frozen=True)
class SetupMutationResult:
    profile: ProfileVersion | None
    goal: GoalVersion | None
    recalculation_preview: TargetPreview | None
    recalculation_restriction: str | None = None


@dataclass(frozen=True)
class TargetConfirmation:
    target: TargetVersion


class TargetServiceError(ApplicationError):
    def __init__(self, code: str, *, status_code: int = 409) -> None:
        super().__init__(
            code=code,
            message=code,
            status_code=status_code,
            processing_mode="deterministic",
        )


@runtime_checkable
class LegacyProfileProjection(Protocol):
    def project(
        self,
        user_id: str,
        profile: ProfileVersion,
        goal: GoalVersion,
        target: TargetVersion,
    ) -> None: ...


class FileLegacyProfileProjection:
    def __init__(self, repository: FitnessRepository) -> None:
        self.repository = repository

    def project(
        self,
        user_id: str,
        profile: ProfileVersion,
        goal: GoalVersion,
        target: TargetVersion,
    ) -> None:
        def update(current):
            return current.model_copy(
                update={
                    "height_cm": profile.height_cm,
                    "weight_kg": profile.weight_kg,
                    "age": profile.age,
                    "goal": goal.goal,
                    "daily_calorie_target": int(target.calories),
                    "daily_protein_target": int(target.protein),
                }
            )

        self.repository.update_profile_atomically(update, user_id)


class ProfileTargetService:
    def __init__(
        self,
        repository: ProfileTargetRepository,
        legacy_projection: LegacyProfileProjection,
    ) -> None:
        self.repository = repository
        self.legacy_projection = legacy_projection

    def get_setup(self, user_id: str) -> ProfileSetupAggregate:
        setup = self.repository.get_setup(user_id)
        return ProfileSetupAggregate(
            profile=setup.profile,
            goal=setup.goal,
            target=setup.target,
            setup_complete=all(
                value is not None
                for value in (setup.profile, setup.goal, setup.target)
            ),
        )

    def update_profile(
        self,
        user_id: str,
        update: ProfileVersionInput,
    ) -> SetupMutationResult:
        profile = self.repository.append_profile_if_changed(user_id, update)
        goal = self.repository.get_latest_goal(user_id)
        preview, restriction = self._preview_after_save(profile, goal)
        return SetupMutationResult(
            profile=profile,
            goal=goal,
            recalculation_preview=preview,
            recalculation_restriction=restriction,
        )

    def update_goal(
        self,
        user_id: str,
        update: GoalVersionInput,
    ) -> SetupMutationResult:
        goal = self.repository.append_goal_if_changed(user_id, update)
        profile = self.repository.get_latest_profile(user_id)
        preview, restriction = self._preview_after_save(profile, goal)
        return SetupMutationResult(
            profile=profile,
            goal=goal,
            recalculation_preview=preview,
            recalculation_restriction=restriction,
        )

    def calculate_preview(
        self,
        user_id: str,
        *,
        manual_targets: DailyTargets | None = None,
    ) -> TargetPreview:
        profile, goal = self._require_profile_and_goal(user_id)
        if manual_targets is None:
            return self._deterministic_preview(profile, goal)

        return self._manual_preview(profile, goal, manual_targets)

    def confirm_target(
        self,
        user_id: str,
        *,
        preview: TargetPreview,
        idempotency_key: str,
        effective_from: str,
        acknowledge_warnings: bool = False,
    ) -> TargetConfirmation:
        _require_uuid(idempotency_key)
        fingerprint = _confirmation_fingerprint(
            preview,
            effective_from=effective_from,
            acknowledge_warnings=acknowledge_warnings,
        )
        try:
            saved = self.repository.get_confirmation(
                user_id,
                idempotency_key,
                fingerprint,
            )
        except ProfileTargetRepositoryError as error:
            raise _repository_error(error) from None
        if saved is not None:
            if saved.projection_completed:
                return TargetConfirmation(target=saved.target)
            return self._project_confirmation(
                user_id,
                idempotency_key,
                fingerprint,
                saved.target,
            )

        profile = self.repository.get_profile_version(
            user_id, preview.profile_version_id
        )
        goal = self.repository.get_goal_version(
            user_id, preview.overall_goal_version_id
        )
        if profile is None or goal is None:
            raise TargetServiceError("TARGET_PREVIEW_STALE", status_code=412)
        if preview.source == "deterministic_calculation":
            expected = self._deterministic_preview(profile, goal)
        elif preview.source == "manual":
            expected = self._manual_preview(profile, goal, preview.targets)
        else:
            raise TargetServiceError("TARGET_PREVIEW_INVALID", status_code=422)
        if expected.preview_token != preview.preview_token:
            raise TargetServiceError("TARGET_PREVIEW_STALE", status_code=412)
        if expected.requires_confirmation and not acknowledge_warnings:
            raise TargetServiceError("TARGET_WARNING_ACKNOWLEDGEMENT_REQUIRED")

        rationale = _target_rationale(expected, acknowledge_warnings)
        target_input = TargetVersionInput(
            profile_version_id=profile.id,
            overall_goal_version_id=goal.id,
            calories=expected.targets.calories,
            carbs=expected.targets.carbs,
            protein=expected.targets.protein,
            fat=expected.targets.fat,
            source=expected.source,
            formula_version=expected.targets.formula_version,
            rationale=rationale,
            effective_from=effective_from,
        )
        try:
            confirmation = self.repository.confirm_target(
                user_id,
                idempotency_key,
                fingerprint,
                target_input,
            )
        except ProfileTargetRepositoryError as error:
            raise _repository_error(error) from None

        if confirmation.projection_completed:
            return TargetConfirmation(target=confirmation.target)

        return self._project_confirmation(
            user_id,
            idempotency_key,
            fingerprint,
            confirmation.target,
        )

    def _project_confirmation(
        self,
        user_id: str,
        idempotency_key: str,
        fingerprint: str,
        target: TargetVersion,
    ) -> TargetConfirmation:

        projection_profile = self.repository.get_profile_version(
            user_id, target.profile_version_id or ""
        )
        projection_goal = self.repository.get_goal_version(
            user_id, target.overall_goal_version_id or ""
        )
        if projection_profile is None or projection_goal is None:
            raise TargetServiceError(
                "TARGET_COMPATIBILITY_WRITE_FAILED", status_code=500
            )

        try:
            self.legacy_projection.project(
                user_id,
                projection_profile,
                projection_goal,
                target,
            )
        except Exception as error:
            raise TargetServiceError(
                "TARGET_COMPATIBILITY_WRITE_FAILED", status_code=500
            ) from error
        try:
            self.repository.mark_projection_complete(
                user_id,
                idempotency_key,
                fingerprint,
            )
        except ProfileTargetRepositoryError as error:
            raise _repository_error(error) from None
        return TargetConfirmation(target=target)

    def list_target_history(self, user_id: str) -> tuple[TargetVersion, ...]:
        return self.repository.list_targets(user_id)

    def _require_profile_and_goal(
        self, user_id: str
    ) -> tuple[ProfileVersion, GoalVersion]:
        setup = self.repository.get_setup(user_id)
        if setup.profile is None or setup.goal is None:
            raise TargetServiceError("PROFILE_TARGET_SETUP_INCOMPLETE")
        return setup.profile, setup.goal

    def _deterministic_preview(
        self,
        profile: ProfileVersion,
        goal: GoalVersion,
    ) -> TargetPreview:
        try:
            targets = _calculate(profile, goal)
        except TargetDomainError as error:
            raise TargetServiceError(error.code, status_code=422) from None
        return _preview(
            profile,
            goal,
            targets,
            source="deterministic_calculation",
            warnings=(),
            requires_confirmation=False,
        )

    def _manual_preview(
        self,
        profile: ProfileVersion,
        goal: GoalVersion,
        manual_targets: DailyTargets,
    ) -> TargetPreview:
        try:
            baseline = _calculate(profile, goal)
        except TargetDomainError:
            baseline = manual_targets
        try:
            validation = evaluate_manual_targets(manual_targets, baseline)
        except TargetDomainError as error:
            raise TargetServiceError(error.code, status_code=422) from None
        manual = DailyTargets(
            calories=manual_targets.calories,
            carbs=manual_targets.carbs,
            protein=manual_targets.protein,
            fat=manual_targets.fat,
        )
        return _preview(
            profile,
            goal,
            manual,
            source="manual",
            warnings=validation.warnings,
            requires_confirmation=validation.requires_confirmation,
        )

    def _preview_after_save(
        self,
        profile: ProfileVersion | None,
        goal: GoalVersion | None,
    ) -> tuple[TargetPreview | None, str | None]:
        if profile is None or goal is None:
            return None, None
        try:
            return self._deterministic_preview(profile, goal), None
        except TargetServiceError as error:
            return None, error.code


def _calculate(profile: ProfileVersion, goal: GoalVersion) -> DailyTargets:
    return calculate_daily_targets(
        ProfileInput(
            age=profile.age,
            height_cm=profile.height_cm,
            weight_kg=profile.weight_kg,
            energy_parameter=profile.energy_parameter,
            activity_level=profile.activity_level,
            auto_target_disabled=profile.auto_target_disabled,
            safety_conditions=profile.safety_conditions,
        ),
        goal.goal,
    )


def _preview(
    profile: ProfileVersion,
    goal: GoalVersion,
    targets: DailyTargets,
    *,
    source: TargetSource,
    warnings: tuple[str, ...],
    requires_confirmation: bool,
) -> TargetPreview:
    payload = {
        "profile_version_id": profile.id,
        "overall_goal_version_id": goal.id,
        "targets": {
            "calories": targets.calories,
            "carbs": targets.carbs,
            "protein": targets.protein,
            "fat": targets.fat,
        },
        "source": source,
        "formula_version": targets.formula_version,
    }
    return TargetPreview(
        profile_version_id=profile.id,
        overall_goal_version_id=goal.id,
        targets=targets,
        source=source,
        warnings=warnings,
        requires_confirmation=requires_confirmation,
        preview_token=_sha256(payload),
    )


def _target_rationale(
    preview: TargetPreview,
    acknowledge_warnings: bool,
) -> dict[str, object]:
    rationale: dict[str, object] = {
        "warnings": list(preview.warnings),
        "confirmed_warnings": (
            list(preview.warnings) if acknowledge_warnings else []
        ),
    }
    if preview.targets.rationale is not None:
        rationale["calculation"] = _json_compatible(
            asdict(preview.targets.rationale)
        )
    return rationale


def _require_uuid(value: str) -> None:
    try:
        UUID(value)
    except (ValueError, AttributeError):
        raise TargetServiceError("INVALID_IDEMPOTENCY_KEY", status_code=422) from None


def _sha256(value: dict[str, object]) -> str:
    canonical = json.dumps(
        _json_compatible(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _confirmation_fingerprint(
    preview: TargetPreview,
    *,
    effective_from: str,
    acknowledge_warnings: bool,
) -> str:
    return _sha256(
        {
            "acknowledge_warnings": acknowledge_warnings,
            "effective_from": effective_from,
            "formula_version": preview.targets.formula_version,
            "overall_goal_version_id": preview.overall_goal_version_id,
            "preview_token": preview.preview_token,
            "profile_version_id": preview.profile_version_id,
            "source": preview.source,
            "targets": {
                "calories": preview.targets.calories,
                "carbs": preview.targets.carbs,
                "protein": preview.targets.protein,
                "fat": preview.targets.fat,
            },
            "warnings": list(preview.warnings),
        }
    )


def _repository_error(error: ProfileTargetRepositoryError) -> TargetServiceError:
    if error.code == "TARGET_PREVIEW_STALE":
        status_code = 412
    elif error.code == "IDEMPOTENCY_KEY_REUSED":
        status_code = 409
    else:
        status_code = 500
    return TargetServiceError(error.code, status_code=status_code)


def _json_compatible(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    return value
