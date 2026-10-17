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
from backend.application.use_cases.interactive_entry import InteractiveEntryService, project_resumed_draft
from backend.api.smart_entry_schemas import (
    InteractionStartRequest, InteractionAnswersRequest, InteractionCorrectionRequest,
    InteractionConfirmRequest, ConfirmedEntryItemsResponse, InteractiveCapabilitiesResponse,
)
from backend.domain.entry_resolution import catalog_signature
from backend.infrastructure.repositories.sqlite_task_budget_repository import SQLiteTaskBudgetRepository
from backend.config import get_settings
from backend.domain.smart_entry import CatalogChoice, ResolvedCandidate
from backend.infrastructure.model_gateway.factory import (
    resolve_user_model_gateway,
)
from backend.infrastructure.settings.file_model_connection_repository import FileModelConnectionRepository
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
        entry_task_ttl_days=get_settings().entry_task_ttl_days,
    )


def get_interactive_entry_service() -> InteractiveEntryService:
    database = get_database()
    settings = get_settings()
    def model_available(user):
        # Metadata admission only. Runtime resolves and decrypts after its guards.
        connection = FileModelConnectionRepository(settings.data_dir).get(user)
        return bool(connection and connection.enabled and connection.encrypted_api_key)
    return InteractiveEntryService(
        SQLiteSmartEntryRepository(database), SQLiteFoodCatalogRepository(database),
        SQLiteTaskBudgetRepository(database), enabled=settings.interactive_entry_enabled,
        gateway_resolver=resolve_user_model_gateway, model_available=model_available,
        mutation_scope=lambda user: user_lifecycle_guard(settings.data_dir, user),
    )


def _interaction_response(service, user, draft):
    result = asdict(draft)
    result['item_commits'] = [asdict(item) for item in service.repository.list_entry_item_commits(user, draft.id)]
    result['dependency_validity'] = []
    for dependency in draft.payload.interaction.dependencies:
        food = service.food_catalog.get_visible_food(user, dependency.catalog_id)
        result['dependency_validity'].append({'item_id': dependency.item_id,
            'catalog_id': dependency.catalog_id,
            'valid': food is not None and catalog_signature(food) == dependency.signature})
    return result


@router.get('/capabilities', response_model=ApiResponse[InteractiveCapabilitiesResponse])
def interactive_capabilities(user: AuthenticatedUser = Depends(require_current_user)):
    settings = get_settings()
    return ok({'interactive_entry_enabled': settings.interactive_entry_enabled,
               'entry_task_ttl_days': settings.entry_task_ttl_days}, processing_mode='deterministic')


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
    interaction_service: InteractiveEntryService = Depends(get_interactive_entry_service),
):
    draft = service.find_latest_draft(
        user.user_id,
        log_date.isoformat(),
    )
    return ok(
        _interaction_response(interaction_service, user.user_id,
            interaction_service.resume(user.user_id, draft.id)) if draft is not None else None,
        processing_mode="deterministic",
    )


@router.get("/{draft_id}", response_model=ApiResponse[SmartEntryDraftResponse])
def get_draft(
    draft_id: str,
    user: AuthenticatedUser = Depends(require_current_user),
    service: InteractiveEntryService = Depends(get_interactive_entry_service),
):
    draft = service.resume(user.user_id, draft_id)
    return ok(_interaction_response(service, user.user_id, draft), processing_mode="deterministic")


@router.post('/{draft_id}/interaction/start', response_model=ApiResponse[SmartEntryDraftResponse])
def start_interaction(draft_id: str, payload: InteractionStartRequest,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    user: AuthenticatedUser = Depends(require_current_user),
    service: InteractiveEntryService = Depends(get_interactive_entry_service)):
    draft = service.start(user.user_id, draft_id, expected_version=payload.expected_version,
                          key=_idempotency_key(idempotency_key))
    return ok(_interaction_response(service, user.user_id, draft),
        processing_mode='agent' if draft.payload.interaction.run_ids else 'deterministic')


@router.post('/{draft_id}/interaction/answers', response_model=ApiResponse[SmartEntryDraftResponse])
def answer_interaction(draft_id: str, payload: InteractionAnswersRequest,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    user: AuthenticatedUser = Depends(require_current_user),
    service: InteractiveEntryService = Depends(get_interactive_entry_service)):
    draft = service.answer(user.user_id, draft_id, **payload.model_dump(),
                           key=_idempotency_key(idempotency_key))
    return ok(_interaction_response(service, user.user_id, draft), processing_mode='deterministic')


@router.post('/{draft_id}/interaction/corrections', response_model=ApiResponse[SmartEntryDraftResponse])
def correct_interaction(draft_id: str, payload: InteractionCorrectionRequest,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    user: AuthenticatedUser = Depends(require_current_user),
    service: InteractiveEntryService = Depends(get_interactive_entry_service)):
    values = payload.model_dump()
    values['updates'] = payload.updates.model_dump(exclude_unset=True)
    draft = service.correct(user.user_id, draft_id, **values, key=_idempotency_key(idempotency_key))
    return ok(_interaction_response(service, user.user_id, draft), processing_mode='deterministic')


@router.post('/{draft_id}/confirm-items', response_model=ApiResponse[ConfirmedEntryItemsResponse])
def confirm_interaction_items(draft_id: str, payload: InteractionConfirmRequest,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    user: AuthenticatedUser = Depends(require_current_user),
    service: InteractiveEntryService = Depends(get_interactive_entry_service)):
    result = service.confirm_items(user.user_id, draft_id, **payload.model_dump(),
        key=_idempotency_key(idempotency_key), timezone_name=preferences_for(user).timezone)
    return ok(asdict(result), processing_mode='deterministic')


@router.patch("/{draft_id}", response_model=ApiResponse[SmartEntryDraftResponse])
def update_draft(
    draft_id: str,
    payload: SmartEntryDraftMutationRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    user: AuthenticatedUser = Depends(require_current_user),
    service: SmartEntryService = Depends(get_smart_entry_service),
    interaction_service: InteractiveEntryService = Depends(get_interactive_entry_service),
):
    draft = service.update_draft(
        user.user_id,
        draft_id,
        expected_version=_version(if_match),
        payload=_payload(payload),
        weight_kg=_weight(user.user_id),
    )
    result = (_interaction_response(interaction_service, user.user_id,
                project_resumed_draft(draft, lambda catalog_id:
                    interaction_service.food_catalog.get_visible_food(user.user_id, catalog_id)))
              if draft.payload.interaction.active else asdict(draft))
    return ok(result, processing_mode="deterministic")


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
