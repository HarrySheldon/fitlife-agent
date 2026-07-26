from __future__ import annotations

from dataclasses import dataclass
import unicodedata

from backend.application.ports.exercise_catalog_repository import (
    ExerciseCatalogItem,
    ExerciseCatalogRepository,
)
from backend.application.ports.food_catalog_repository import (
    FoodCatalogItem,
    FoodCatalogRepository,
)
from backend.domain.meals import (
    FoodDefinition,
    MealDomainError,
    portion_from_food,
)
from backend.domain.smart_entry import ParsedEntry, ParsedSegment
from backend.domain.workouts import WorkoutDomainError, cardio_calories


@dataclass(frozen=True)
class CatalogChoice:
    id: str
    name: str
    source: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedCandidate:
    id: str
    kind: str
    raw_text: str
    normalized_text: str
    subject_text: str
    meal_context: str | None
    selected: bool
    selected_catalog_id: str | None
    catalog_choices: tuple[CatalogChoice, ...]
    issues: tuple[str, ...]
    values: dict[str, object]
    provenance: dict[str, object]
    assumptions: tuple[str, ...] = ()
    agent_estimate_accepted: bool = False


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
