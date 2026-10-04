from __future__ import annotations

from dataclasses import asdict
from datetime import date
import re
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request

from backend.api.dependencies import require_current_user
from backend.api.preference_context import preferences_for
from backend.api.smart_entry_schemas import (
    ConfirmedSmartEntryResponse,
    DeletedSmartEntryResponse,
    SmartCandidateModel,
    SmartEntryCreateRequest,
    SmartEntryDraftMutationRequest,
    SmartEntryDraftResponse,
)
from backend.api.utils import ok, request_id_for
from backend.application.ports.smart_entry_repository import (
    SmartEntryDraftPayload,
)
from backend.application.use_cases.smart_entry import (
    SmartEntryService,
    SmartEntryServiceError,
)
from backend.config import get_settings
from backend.domain.smart_entry import CatalogChoice, ResolvedCandidate
from backend.infrastructure.model_gateway.factory import (
    resolve_user_model_gateway,
)
from backend.infrastructure.repositories.sqlite_exercise_catalog_repository import (
    SQLiteExerciseCatalogRepository,
)
from backend.infrastructure.repositories.sqlite_food_catalog_repository import (
    SQLiteFoodCatalogRepository,
)
from backend.infrastructure.repositories.sqlite_profile_target_repository import (
    SQLiteProfileTargetRepository,
)
from backend.infrastructure.repositories.sqlite_smart_entry_repository import (
    SQLiteSmartEntryRepository,
)
from backend.infrastructure.sqlite.runtime import get_database
from backend.infrastructure.user_lifecycle import user_lifecycle_guard
from backend.schemas import ApiResponse, AuthenticatedUser


router = APIRouter(prefix="/api/v1/smart-entry-drafts")


def get_smart_entry_service() -> SmartEntryService:
    database = get_database()
    return SmartEntryService(
        SQLiteSmartEntryRepository(database),
        SQLiteFoodCatalogRepository(database),
        SQLiteExerciseCatalogRepository(database),
        mutation_scope=lambda user_id: user_lifecycle_guard(
            get_settings().data_dir,
            user_id,
        ),
        gateway_resolver=resolve_user_model_gateway,
    )


@router.post("", response_model=ApiResponse[SmartEntryDraftResponse])
def create_draft(
    payload: SmartEntryCreateRequest,
    user: AuthenticatedUser = Depends(require_current_user),
    service: SmartEntryService = Depends(get_smart_entry_service),
):
    draft = service.create_draft(
        user.user_id,
        log_date=payload.log_date.isoformat(),
        raw_text=payload.raw_text,
        weight_kg=_weight(user.user_id),
    )
    return ok(asdict(draft), processing_mode="deterministic")


@router.get("", response_model=ApiResponse[SmartEntryDraftResponse | None])
def find_latest_draft(
    log_date: date = Query(alias="date"),
    user: AuthenticatedUser = Depends(require_current_user),
    service: SmartEntryService = Depends(get_smart_entry_service),
):
    draft = service.find_latest_draft(
        user.user_id,
        log_date.isoformat(),
    )
    return ok(
        asdict(draft) if draft is not None else None,
        processing_mode="deterministic",
    )


@router.get("/{draft_id}", response_model=ApiResponse[SmartEntryDraftResponse])
def get_draft(
    draft_id: str,
    user: AuthenticatedUser = Depends(require_current_user),
    service: SmartEntryService = Depends(get_smart_entry_service),
):
    draft = service.get_draft(user.user_id, draft_id)
    if draft is None:
        raise SmartEntryServiceError("DRAFT_NOT_FOUND", status_code=404)
    return ok(asdict(draft), processing_mode="deterministic")


@router.patch("/{draft_id}", response_model=ApiResponse[SmartEntryDraftResponse])
def update_draft(
    draft_id: str,
    payload: SmartEntryDraftMutationRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    user: AuthenticatedUser = Depends(require_current_user),
    service: SmartEntryService = Depends(get_smart_entry_service),
):
    draft = service.update_draft(
        user.user_id,
        draft_id,
        expected_version=_version(if_match),
        payload=_payload(payload),
        weight_kg=_weight(user.user_id),
    )
    return ok(asdict(draft), processing_mode="deterministic")


@router.delete(
    "/{draft_id}",
    response_model=ApiResponse[DeletedSmartEntryResponse],
)
def delete_draft(
    draft_id: str,
    user: AuthenticatedUser = Depends(require_current_user),
    service: SmartEntryService = Depends(get_smart_entry_service),
):
    service.delete_draft(user.user_id, draft_id)
    return ok({"deleted": True}, processing_mode="deterministic")


@router.post(
    "/{draft_id}/analyze",
    response_model=ApiResponse[SmartEntryDraftResponse],
)
def analyze_draft(
    draft_id: str,
    http_request: Request,
    if_match: str | None = Header(default=None, alias="If-Match"),
    user: AuthenticatedUser = Depends(require_current_user),
    service: SmartEntryService = Depends(get_smart_entry_service),
):
    preferences = preferences_for(user)
    draft = service.analyze_draft(
        user.user_id,
        draft_id,
        expected_version=_version(if_match),
        locale=preferences.language,
        weight_kg=_weight(user.user_id),
        request_id=request_id_for(http_request),
    )
    return ok(asdict(draft), processing_mode="agent")


@router.post(
    "/{draft_id}/confirm",
    response_model=ApiResponse[ConfirmedSmartEntryResponse],
)
def confirm_draft(
    draft_id: str,
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
    ),
    user: AuthenticatedUser = Depends(require_current_user),
    service: SmartEntryService = Depends(get_smart_entry_service),
):
    confirmed = service.confirm_draft(
        user.user_id,
        draft_id,
        expected_version=_version(if_match),
        idempotency_key=_idempotency_key(idempotency_key),
        timezone_name=preferences_for(user).timezone,
    )
    return ok(asdict(confirmed), processing_mode="deterministic")


def _payload(value: SmartEntryDraftMutationRequest) -> SmartEntryDraftPayload:
    return SmartEntryDraftPayload(
        log_date=value.log_date.isoformat(),
        raw_text=value.raw_text,
        parser_version=value.parser_version,
        candidates=tuple(_candidate(item) for item in value.candidates),
    )


def _candidate(value: SmartCandidateModel) -> ResolvedCandidate:
    return ResolvedCandidate(
        id=value.id,
        kind=value.kind,
        raw_text=value.raw_text,
        normalized_text=value.normalized_text,
        subject_text=value.subject_text,
        meal_context=value.meal_context,
        selected=value.selected,
        selected_catalog_id=value.selected_catalog_id,
        catalog_choices=tuple(
            CatalogChoice(
                id=item.id,
                name=item.name,
                source=item.source,
                aliases=tuple(item.aliases),
            )
            for item in value.catalog_choices
        ),
        issues=tuple(value.issues),
        values=value.values,
        provenance=value.provenance,
        assumptions=tuple(value.assumptions),
        agent_estimate_accepted=value.agent_estimate_accepted,
    )


def _weight(user_id: str) -> float | None:
    profile = SQLiteProfileTargetRepository(
        get_database()
    ).get_latest_profile(user_id)
    return profile.weight_kg if profile is not None else None


def _version(value: str | None) -> int:
    if value is None:
        raise SmartEntryServiceError(
            "DRAFT_VERSION_REQUIRED",
            status_code=422,
        )
    token = value.strip()
    if re.fullmatch(r'(?:[1-9]\d{0,18}|"[1-9]\d{0,18}")', token) is None:
        raise SmartEntryServiceError(
            "DRAFT_VERSION_INVALID",
            status_code=422,
        )
    version = int(token.strip('"'))
    if version > 9_223_372_036_854_775_807:
        raise SmartEntryServiceError(
            "DRAFT_VERSION_INVALID",
            status_code=422,
        )
    return version


def _idempotency_key(value: str | None) -> str:
    if value is None:
        raise SmartEntryServiceError(
            "IDEMPOTENCY_KEY_REQUIRED",
            status_code=422,
        )
    try:
        return str(UUID(value))
    except (AttributeError, ValueError):
        raise SmartEntryServiceError(
            "INVALID_IDEMPOTENCY_KEY",
            status_code=422,
        ) from None
