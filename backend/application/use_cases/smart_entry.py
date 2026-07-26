from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import unicodedata
from uuid import UUID

from backend.agent.smart_entry_analyzer import (
    PROMPT_VERSION,
    SmartEntryAnalysisResponse,
    analyze_smart_entry,
)
from backend.application.ports.exercise_catalog_repository import (
    ExerciseCatalogItem,
    ExerciseCatalogRepository,
)
from backend.application.ports.food_catalog_repository import (
    FoodCatalogItem,
    FoodCatalogRepository,
)
from backend.application.ports.smart_entry_repository import (
    ConfirmedSmartEntry,
    SmartEntryDraft,
    SmartEntryDraftPayload,
    SmartEntryRepository,
    SmartEntryRepositoryError,
)
from backend.application.ports.structured_model_gateway import (
    StructuredModelGateway,
)
from backend.domain.errors import ApplicationError, model_gateway_error
from backend.domain.meals import (
    FoodDefinition,
    MealDomainError,
    portion_from_food,
)
from backend.domain.smart_entry import (
    CatalogChoice,
    ParsedEntry,
    ParsedSegment,
    ResolvedCandidate,
    parse_entry_text,
)
from backend.domain.workouts import WorkoutDomainError, cardio_calories


Clock = Callable[[], datetime]
GatewayResolver = Callable[[str], StructuredModelGateway]


class SmartEntryServiceError(ApplicationError):
    def __init__(self, code: str, *, status_code: int) -> None:
        super().__init__(
            code=code,
            message=code,
            status_code=status_code,
            processing_mode="deterministic",
        )


class SmartEntryService:
    def __init__(
        self,
        repository: SmartEntryRepository,
        food_catalog: FoodCatalogRepository,
        exercise_catalog: ExerciseCatalogRepository,
        *,
        clock: Clock | None = None,
        mutation_scope: Callable[[str], AbstractContextManager] | None = None,
        gateway_resolver: GatewayResolver | None = None,
    ) -> None:
        self.repository = repository
        self.food_catalog = food_catalog
        self.exercise_catalog = exercise_catalog
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._mutation_scope = mutation_scope or (lambda _user_id: nullcontext())
        self._gateway_resolver = gateway_resolver

    def create_draft(
        self,
        user_id: str,
        *,
        log_date: str,
        raw_text: str,
        weight_kg: float | None,
    ) -> SmartEntryDraft:
        parsed = parse_entry_text(raw_text)
        payload = SmartEntryDraftPayload(
            log_date=log_date,
            raw_text=parsed.raw_text,
            parser_version=parsed.parser_version,
            candidates=resolve_candidates(
                user_id,
                parsed,
                food_catalog=self.food_catalog,
                exercise_catalog=self.exercise_catalog,
                weight_kg=weight_kg,
            ),
        )
        expiry = _timestamp(self._clock() + timedelta(days=30))
        with self._mutation_scope(user_id):
            try:
                return self.repository.create_draft(
                    user_id,
                    payload,
                    expires_at=expiry,
                )
            except SmartEntryRepositoryError as error:
                raise _service_error(error) from None

    def get_draft(
        self,
        user_id: str,
        draft_id: str,
    ) -> SmartEntryDraft | None:
        try:
            return self.repository.get_draft(user_id, draft_id)
        except SmartEntryRepositoryError as error:
            raise _service_error(error) from None

    def find_latest_draft(
        self,
        user_id: str,
        log_date: str,
    ) -> SmartEntryDraft | None:
        try:
            return self.repository.find_latest_draft(user_id, log_date)
        except SmartEntryRepositoryError as error:
            raise _service_error(error) from None

    def update_draft(
        self,
        user_id: str,
        draft_id: str,
        *,
        expected_version: int,
        payload: SmartEntryDraftPayload,
    ) -> SmartEntryDraft:
        with self._mutation_scope(user_id):
            try:
                return self.repository.update_draft(
                    user_id,
                    draft_id,
                    expected_version=expected_version,
                    payload=payload,
                )
            except SmartEntryRepositoryError as error:
                raise _service_error(error) from None

    def delete_draft(self, user_id: str, draft_id: str) -> None:
        with self._mutation_scope(user_id):
            try:
                self.repository.delete_draft(user_id, draft_id)
            except SmartEntryRepositoryError as error:
                raise _service_error(error) from None

    def analyze_draft(
        self,
        user_id: str,
        draft_id: str,
        *,
        expected_version: int,
        locale: str,
        weight_kg: float | None,
    ) -> SmartEntryDraft:
        draft = self.get_draft(user_id, draft_id)
        if draft is None:
            raise SmartEntryServiceError("DRAFT_NOT_FOUND", status_code=404)
        if draft.version != expected_version:
            raise _agent_service_error(
                "DRAFT_VERSION_CONFLICT",
                status_code=409,
            )
        if self._gateway_resolver is None:
            error = _agent_service_error(
                "AI_NOT_CONFIGURED",
                status_code=409,
            )
            self._mark_analysis_failed(
                user_id,
                draft,
                error,
                model=None,
            )
            raise error

        gateway: StructuredModelGateway | None = None
        try:
            gateway = self._gateway_resolver(user_id)
            result = analyze_smart_entry(
                gateway,
                draft.payload.candidates,
                locale=locale,
                weight_kg=weight_kg,
            )
            output = SmartEntryAnalysisResponse.model_validate(result.output)
            payload = replace(
                draft.payload,
                candidates=_merge_analysis(
                    draft.payload.candidates,
                    output,
                ),
            )
        except ApplicationError as error:
            self._mark_analysis_failed(
                user_id,
                draft,
                error,
                model=getattr(gateway, "model", None),
            )
            raise
        except Exception as error:
            normalized = model_gateway_error(error)
            self._mark_analysis_failed(
                user_id,
                draft,
                normalized,
                model=getattr(gateway, "model", None),
            )
            raise normalized from None

        with self._mutation_scope(user_id):
            try:
                return self.repository.save_analysis(
                    user_id,
                    draft_id,
                    expected_version=expected_version,
                    payload=payload,
                    prompt_version=PROMPT_VERSION,
                    model=result.model,
                    metadata={"usage": result.usage},
                )
            except SmartEntryRepositoryError as error:
                raise _agent_repository_error(error) from None

    def confirm_draft(
        self,
        user_id: str,
        draft_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
        timezone_name: str = "UTC",
    ) -> ConfirmedSmartEntry:
        key = _uuid(idempotency_key)
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "draft_id": draft_id,
                    "expected_version": expected_version,
                    "user_id": user_id,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with self._mutation_scope(user_id):
            try:
                return self.repository.confirm(
                    user_id,
                    draft_id,
                    expected_version=expected_version,
                    idempotency_key=key,
                    request_fingerprint=fingerprint,
                    timezone_name=timezone_name,
                )
            except SmartEntryRepositoryError as error:
                raise _service_error(error) from None

    def _mark_analysis_failed(
        self,
        user_id: str,
        draft: SmartEntryDraft,
        error: ApplicationError,
        *,
        model: str | None,
    ) -> None:
        with self._mutation_scope(user_id):
            try:
                self.repository.mark_agent_failed(
                    user_id,
                    draft.id,
                    expected_version=draft.version,
                    prompt_version=PROMPT_VERSION,
                    model=model,
                    metadata={"error_code": error.code},
                )
            except SmartEntryRepositoryError as repository_error:
                raise _agent_repository_error(repository_error) from None


def resolve_candidates(
    user_id: str,
    parsed: ParsedEntry,
    *,
    food_catalog: FoodCatalogRepository,
    exercise_catalog: ExerciseCatalogRepository,
    weight_kg: float | None,
) -> tuple[ResolvedCandidate, ...]:
    return tuple(
        _resolve_segment(
            user_id,
            segment,
            food_catalog=food_catalog,
            exercise_catalog=exercise_catalog,
            weight_kg=weight_kg,
        )
        for segment in parsed.segments
    )


def _resolve_segment(
    user_id: str,
    segment: ParsedSegment,
    *,
    food_catalog: FoodCatalogRepository,
    exercise_catalog: ExerciseCatalogRepository,
    weight_kg: float | None,
) -> ResolvedCandidate:
    if segment.kind == "food":
        results = food_catalog.search(user_id, segment.subject_text, limit=10)
        exact = _exact_matches(segment.subject_text, results)
        return _food_candidate(segment, results, exact)
    if segment.kind in {"strength", "cardio"}:
        results = exercise_catalog.search(
            user_id,
            segment.subject_text,
            limit=10,
        )
        compatible = tuple(
            item for item in results if item.exercise_type == segment.kind
        )
        exact = _exact_matches(segment.subject_text, compatible)
        return _exercise_candidate(
            segment,
            compatible,
            exact,
            weight_kg=weight_kg,
        )
    return _base_candidate(
        segment,
        issues=segment.issues,
        choices=(),
    )


def _food_candidate(
    segment: ParsedSegment,
    results: tuple[FoodCatalogItem, ...],
    exact: tuple[FoodCatalogItem, ...],
) -> ResolvedCandidate:
    choices = tuple(_choice(item) for item in (exact or results))
    if len(exact) != 1:
        code = (
            "SMART_ENTRY_CATALOG_AMBIGUOUS"
            if len(exact) > 1
            else "SMART_ENTRY_CATALOG_UNMATCHED"
        )
        return _base_candidate(
            segment,
            issues=_append_issue(segment.issues, code),
            choices=choices,
        )
    item = exact[0]
    if segment.food_amount is None or segment.food_unit is None:
        return _base_candidate(
            segment,
            issues=segment.issues,
            choices=choices,
            selected_catalog_id=item.id,
            provenance=_food_provenance(item),
        )
    definition = FoodDefinition(
        name=item.name,
        basis_type=item.basis_type,
        basis_amount=item.basis_amount,
        unit=item.unit,
        calories=item.calories,
        carbs=item.carbs,
        protein=item.protein,
        fat=item.fat,
        source=item.source,
    )
    try:
        portion = portion_from_food(
            definition,
            amount=segment.food_amount,
            unit=segment.food_unit,
        )
    except MealDomainError:
        return _base_candidate(
            segment,
            issues=_append_issue(
                segment.issues,
                "SMART_ENTRY_FOOD_UNIT_INCOMPATIBLE",
            ),
            choices=choices,
            selected_catalog_id=item.id,
            provenance=_food_provenance(item),
        )
    return _base_candidate(
        segment,
        issues=segment.issues,
        choices=choices,
        selected_catalog_id=item.id,
        values={
            "name": portion.food_name,
            "amount": portion.amount,
            "unit": portion.unit,
            "basis_type": portion.basis_type,
            "calories": portion.calories,
            "carbs": portion.carbs,
            "protein": portion.protein,
            "fat": portion.fat,
            "source": portion.source,
            "is_estimate": False,
        },
        provenance=_food_provenance(item),
    )


def _exercise_candidate(
    segment: ParsedSegment,
    results: tuple[ExerciseCatalogItem, ...],
    exact: tuple[ExerciseCatalogItem, ...],
    *,
    weight_kg: float | None,
) -> ResolvedCandidate:
    choices = tuple(_choice(item) for item in (exact or results))
    if len(exact) != 1:
        code = (
            "SMART_ENTRY_CATALOG_AMBIGUOUS"
            if len(exact) > 1
            else "SMART_ENTRY_CATALOG_UNMATCHED"
        )
        return _base_candidate(
            segment,
            issues=_append_issue(segment.issues, code),
            choices=choices,
        )
    item = exact[0]
    values: dict[str, object] = {
        "name": item.name,
        "exercise_type": item.exercise_type,
        "primary_muscle": item.primary_muscle,
        "secondary_muscles": item.secondary_muscles,
        "met": item.met,
        "set_count": segment.set_count,
        "reps": segment.reps,
        "load_kg": segment.load_kg,
        "bodyweight": segment.bodyweight,
        "duration_min": segment.duration_min,
        "device_calories": segment.device_calories,
    }
    if segment.kind == "cardio" and segment.duration_min is not None:
        try:
            estimate = cardio_calories(
                duration_min=segment.duration_min,
                device_calories=segment.device_calories,
                met=item.met,
                weight_kg=weight_kg,
            )
        except WorkoutDomainError:
            pass
        else:
            values.update(
                {
                    "estimated_calories": estimate.calories,
                    "is_estimate": estimate.is_estimate,
                    "estimate_method": estimate.method,
                    "estimate_formula_version": estimate.formula_version,
                    "estimate_inputs": estimate.inputs,
                }
            )
    return _base_candidate(
        segment,
        issues=segment.issues,
        choices=choices,
        selected_catalog_id=item.id,
        values=values,
        provenance=_exercise_provenance(item),
    )


def _base_candidate(
    segment: ParsedSegment,
    *,
    issues: tuple[str, ...],
    choices: tuple[CatalogChoice, ...],
    selected_catalog_id: str | None = None,
    values: dict[str, object] | None = None,
    provenance: dict[str, object] | None = None,
) -> ResolvedCandidate:
    return ResolvedCandidate(
        id=segment.id,
        kind=segment.kind,
        raw_text=segment.raw_text,
        normalized_text=segment.normalized_text,
        subject_text=segment.subject_text,
        meal_context=segment.meal_context,
        selected=True,
        selected_catalog_id=selected_catalog_id,
        catalog_choices=choices,
        issues=issues,
        values=values or _explicit_values(segment),
        provenance=provenance or {},
    )


def _explicit_values(segment: ParsedSegment) -> dict[str, object]:
    return {
        "amount": segment.food_amount,
        "unit": segment.food_unit,
        "set_count": segment.set_count,
        "reps": segment.reps,
        "load_kg": segment.load_kg,
        "bodyweight": segment.bodyweight,
        "duration_min": segment.duration_min,
        "device_calories": segment.device_calories,
    }


def _exact_matches(query: str, items: tuple) -> tuple:
    normalized = _key(query)
    return tuple(
        item
        for item in items
        if normalized in {_key(item.name), *(_key(alias) for alias in item.aliases)}
    )


def _key(value: str) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", value).casefold().strip().split()
    )


def _choice(item) -> CatalogChoice:
    return CatalogChoice(
        id=item.id,
        name=item.name,
        source=item.source,
        aliases=item.aliases,
    )


def _food_provenance(item: FoodCatalogItem) -> dict[str, object]:
    return {
        "catalog_id": item.id,
        "source": item.source,
        "source_name": item.source_name,
        "source_record_id": item.source_record_id,
        "dataset_version": item.dataset_version,
        "license": item.license,
        "attribution": item.attribution,
        "content_hash": item.content_hash,
        **item.provenance,
    }


def _exercise_provenance(item: ExerciseCatalogItem) -> dict[str, object]:
    return {
        "catalog_id": item.id,
        "source": item.source,
        "source_name": item.source_name,
        "source_record_id": item.source_record_id,
        "dataset_version": item.dataset_version,
        "license": item.license,
        "attribution": item.attribution,
        "content_hash": item.content_hash,
        **item.provenance,
    }


def _append_issue(issues: tuple[str, ...], code: str) -> tuple[str, ...]:
    return issues if code in issues else (*issues, code)


def _merge_analysis(
    candidates: tuple[ResolvedCandidate, ...],
    output: SmartEntryAnalysisResponse,
) -> tuple[ResolvedCandidate, ...]:
    candidate_by_id = {candidate.id: candidate for candidate in candidates}
    patches: dict[str, ResolvedCandidate] = {}
    for suggestion in output.food_suggestions:
        candidate = _analysis_target(
            candidate_by_id,
            patches,
            suggestion.candidate_id,
        )
        values = {
            **candidate.values,
            "name": suggestion.canonical_name,
            "amount": candidate.values.get("amount") or 1,
            "unit": candidate.values.get("unit") or "serving",
            "basis_type": "per_serving",
            "calories": suggestion.calories.value,
            "carbs": suggestion.carbs.value,
            "protein": suggestion.protein.value,
            "fat": suggestion.fat.value,
            "source": "agent_estimate",
            "is_estimate": True,
            "serving_assumption": suggestion.serving_assumption,
            "uncertainty": {
                "calories": _estimate_range(suggestion.calories),
                "carbs": _estimate_range(suggestion.carbs),
                "protein": _estimate_range(suggestion.protein),
                "fat": _estimate_range(suggestion.fat),
            },
        }
        patches[candidate.id] = replace(
            candidate,
            kind="food",
            issues=_analysis_issues(
                candidate.issues,
                resolved_codes={
                    "SMART_ENTRY_KIND_UNRESOLVED",
                    "SMART_ENTRY_CATALOG_UNMATCHED",
                    "SMART_ENTRY_CATALOG_AMBIGUOUS",
                    "SMART_ENTRY_FOOD_AMOUNT_REQUIRED",
                },
            ),
            values=values,
            provenance={
                **candidate.provenance,
                "source": "agent_estimate",
                "prompt_version": PROMPT_VERSION,
            },
            assumptions=tuple(suggestion.assumptions),
            agent_estimate_accepted=False,
        )
    for suggestion in output.exercise_suggestions:
        candidate = _analysis_target(
            candidate_by_id,
            patches,
            suggestion.candidate_id,
        )
        values = {
            **candidate.values,
            "name": suggestion.canonical_name,
            "exercise_type": suggestion.exercise_type,
            "primary_muscle": suggestion.primary_muscle,
            "secondary_muscles": suggestion.secondary_muscles,
            "met": suggestion.met.value if suggestion.met is not None else None,
            "met_uncertainty": (
                _estimate_range(suggestion.met)
                if suggestion.met is not None
                else None
            ),
            "source": "agent_estimate",
            "is_estimate": True,
        }
        patches[candidate.id] = replace(
            candidate,
            kind=suggestion.exercise_type,
            issues=_analysis_issues(
                candidate.issues,
                resolved_codes={
                    "SMART_ENTRY_KIND_UNRESOLVED",
                    "SMART_ENTRY_CATALOG_UNMATCHED",
                    "SMART_ENTRY_CATALOG_AMBIGUOUS",
                },
            ),
            values=values,
            provenance={
                **candidate.provenance,
                "source": "agent_estimate",
                "prompt_version": PROMPT_VERSION,
            },
            assumptions=tuple(suggestion.assumptions),
            agent_estimate_accepted=False,
        )
    return tuple(patches.get(candidate.id, candidate) for candidate in candidates)


def _analysis_target(
    candidates: dict[str, ResolvedCandidate],
    patches: dict[str, ResolvedCandidate],
    candidate_id: str,
) -> ResolvedCandidate:
    candidate = candidates.get(candidate_id)
    if candidate is None or candidate_id in patches or not candidate.issues:
        raise ValueError("Agent returned an invalid candidate reference")
    return candidate


def _analysis_issues(
    issues: tuple[str, ...],
    *,
    resolved_codes: set[str],
) -> tuple[str, ...]:
    remaining = tuple(code for code in issues if code not in resolved_codes)
    return _append_issue(
        remaining,
        "SMART_ENTRY_AGENT_ESTIMATE_ACCEPTANCE_REQUIRED",
    )


def _estimate_range(estimate) -> dict[str, object]:
    return {
        "min": estimate.min_value,
        "max": estimate.max_value,
        "basis": estimate.basis,
    }


def _service_error(error: SmartEntryRepositoryError) -> SmartEntryServiceError:
    status = {
        "DRAFT_NOT_FOUND": 404,
        "DRAFT_EXPIRED": 410,
        "DRAFT_VERSION_CONFLICT": 409,
        "SMART_ENTRY_DRAFT_CORRUPT": 500,
        "DRAFT_UPDATE_FAILED": 500,
        "IDEMPOTENCY_KEY_REUSED": 409,
        "SMART_ENTRY_CONFIRM_FAILED": 500,
        "IDEMPOTENCY_RESPONSE_CORRUPT": 500,
    }.get(error.code, 422)
    return SmartEntryServiceError(error.code, status_code=status)


def _agent_repository_error(
    error: SmartEntryRepositoryError,
) -> ApplicationError:
    deterministic = _service_error(error)
    return _agent_service_error(
        deterministic.code,
        status_code=deterministic.status_code,
    )


def _agent_service_error(code: str, *, status_code: int) -> ApplicationError:
    return ApplicationError(
        code=code,
        message=code,
        status_code=status_code,
        processing_mode="agent",
    )


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00",
        "Z",
    )


def _uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except (AttributeError, TypeError, ValueError):
        raise SmartEntryServiceError(
            "INVALID_IDEMPOTENCY_KEY",
            status_code=422,
        ) from None
