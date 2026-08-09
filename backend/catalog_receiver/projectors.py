from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import jmespath
from pydantic import ValidationError

from backend.catalog_receiver.mapping import resolve_field, select_value
from backend.catalog_receiver.models import (
    CanonicalExerciseRecord,
    CanonicalFoodRecord,
    CsvSource,
    JsonSource,
    MappingProfile,
    ProjectionResult,
    ReceiverError,
    ReceiverIssue,
    SourceDocument,
)


def project_source(
    source: SourceDocument,
    profile: MappingProfile,
    *,
    enrichment_path: str | Path | None = None,
) -> ProjectionResult:
    if source.metadata.kind != profile.input_format:
        raise ReceiverError(
            "MAPPING_SOURCE_FORMAT_MISMATCH",
            f"Profile expects {profile.input_format}, got {source.metadata.kind}.",
            exit_code=3,
        )
    if profile.catalog_kind == "food":
        if not isinstance(source, CsvSource) or profile.projection.strategy != "grouped_pivot":
            raise ReceiverError(
                "MAPPING_PROJECTION_UNSUPPORTED",
                "The built-in food projector requires grouped-pivot CSV input.",
                exit_code=3,
            )
        return _project_foods(source, profile)
    if not isinstance(source, JsonSource) or profile.projection.strategy != "row":
        raise ReceiverError(
            "MAPPING_PROJECTION_UNSUPPORTED",
            "The built-in exercise projector requires row JSON input.",
            exit_code=3,
        )
    return _project_exercises(source, profile, enrichment_path=enrichment_path)


def _project_foods(source: CsvSource, profile: MappingProfile) -> ProjectionResult:
    projection = profile.projection
    assert projection.grouping_key is not None
    assert projection.pivot is not None
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    issues: list[ReceiverIssue] = []
    for row_index, row in enumerate(source.rows, start=2):
        identity = _text(select_value(row, projection.grouping_key))
        if not identity:
            issues.append(_issue("REQUIRED_VALUE_MISSING", row_index, projection.grouping_key))
            continue
        groups[identity].append(row)

    records: list[CanonicalFoodRecord] = []
    rejected = 0
    for identity, rows in groups.items():
        group_issues = _food_group_issues(identity, rows, profile)
        if group_issues:
            issues.extend(group_issues)
            rejected += 1
            continue
        first = rows[0]
        values = {name: resolve_field(first, spec) for name, spec in projection.fields.items()}
        nutrients = _pivot_nutrients(rows, profile)
        aliases = _unique_text(
            (
                values.get("traditional_name"),
                values.get("common_name"),
                values.get("english_name"),
            )
        )
        try:
            records.append(
                CanonicalFoodRecord(
                    source_name=profile.source_name,
                    source_record_id=identity,
                    dataset_version=profile.dataset_version,
                    license=profile.license,
                    attribution=profile.attribution,
                    name=_text(values.get("name")) or "",
                    calories=nutrients["calories"],
                    carbs=nutrients["carbs"],
                    protein=nutrients["protein"],
                    fat=nutrients["fat"],
                    aliases=aliases,
                    provenance={
                        "profile": f"{profile.profile_name}@{profile.profile_version}",
                        "food_category": values.get("food_category"),
                        "description": values.get("description"),
                        "nutrient_basis": "每100克含量",
                        "name_conversion": "opencc_t2s",
                    },
                )
            )
        except ValidationError as error:
            issues.append(
                _issue(
                    "CANONICAL_RECORD_INVALID",
                    identity,
                    None,
                    observed=error.errors(include_url=False),
                )
            )
            rejected += 1
    return ProjectionResult(
        catalog_kind="food",
        records=tuple(records),
        issues=tuple(issues),
        scanned_count=len(groups),
        rejected_count=rejected,
    )


def _food_group_issues(
    identity: str,
    rows: list[dict[str, str]],
    profile: MappingProfile,
) -> list[ReceiverIssue]:
    projection = profile.projection
    issues: list[ReceiverIssue] = []
    for field_name, field in projection.fields.items():
        if field.selector is None or field_name not in {
            "traditional_name",
            "common_name",
            "english_name",
            "food_category",
            "description",
        }:
            continue
        values = _unique_text(select_value(row, field.selector) for row in rows)
        if field_name == "traditional_name" and not values:
            issues.append(_issue("REQUIRED_VALUE_MISSING", identity, field_name))
        elif len(values) > 1:
            issues.append(
                _issue("GROUP_DESCRIPTOR_INCONSISTENT", identity, field_name, observed=values)
            )
    pivot = projection.pivot
    assert pivot is not None
    for target, labels in pivot.targets.items():
        selected = [
            row
            for label in labels
            for row in rows
            if _text(select_value(row, pivot.key_selector)) == label
        ]
        if not selected:
            issues.append(_issue("REQUIRED_NUTRIENT_MISSING", identity, target))
            continue
        preferred_label = next(
            label
            for label in labels
            if any(_text(select_value(row, pivot.key_selector)) == label for row in selected)
        )
        preferred = [
            row
            for row in selected
            if _text(select_value(row, pivot.key_selector)) == preferred_label
        ]
        if len(preferred) != 1:
            issues.append(_issue("NUTRIENT_DUPLICATE", identity, target, observed=len(preferred)))
            continue
        if pivot.unit_selector:
            unit = _text(select_value(preferred[0], pivot.unit_selector))
            expected = "kcal" if target == "calories" else "g"
            if unit != expected:
                issues.append(
                    _issue("NUTRIENT_UNIT_UNSUPPORTED", identity, target, observed=unit, expected=expected)
                )
        try:
            value = float(_text(select_value(preferred[0], pivot.value_selector)).replace(",", ""))
            if value < 0:
                raise ValueError
        except (TypeError, ValueError):
            issues.append(_issue("VALUE_NUMBER_INVALID", identity, target))
    return issues


def _pivot_nutrients(
    rows: list[dict[str, str]],
    profile: MappingProfile,
) -> dict[str, float]:
    pivot = profile.projection.pivot
    assert pivot is not None
    result: dict[str, float] = {}
    for target, labels in pivot.targets.items():
        for label in labels:
            selected = next(
                (
                    row
                    for row in rows
                    if _text(select_value(row, pivot.key_selector)) == label
                ),
                None,
            )
            if selected is not None:
                result[target] = float(
                    _text(select_value(selected, pivot.value_selector)).replace(",", "")
                )
                break
    return result


def _project_exercises(
    source: JsonSource,
    profile: MappingProfile,
    *,
    enrichment_path: str | Path | None,
) -> ProjectionResult:
    selector = profile.projection.record_selector or "@"
    raw_records = jmespath.search(selector, source.document)
    if not isinstance(raw_records, list) or any(not isinstance(item, dict) for item in raw_records):
        raise ReceiverError(
            "MAPPING_RECORD_SELECTOR_INVALID",
            "Exercise record selector must resolve to an array of objects.",
            exit_code=3,
        )
    enrichments = _load_enrichment(enrichment_path) if enrichment_path else {}
    source_ids = {
        _text(resolve_field(item, profile.projection.fields["source_record_id"]))
        for item in raw_records
    }
    issues: list[ReceiverIssue] = []
    for orphan in sorted(set(enrichments) - source_ids):
        issues.append(_issue("ENRICHMENT_ORPHAN", orphan, "source_record_id", severity="warning"))

    records: list[CanonicalExerciseRecord] = []
    excluded = rejected = enriched = 0
    for index, raw in enumerate(raw_records, start=1):
        values = {
            name: resolve_field(raw, spec)
            for name, spec in profile.projection.fields.items()
        }
        source_id = _text(values.get("source_record_id"))
        upstream_name = _text(values.get("name"))
        category = _text(values.get("exercise_type")).casefold()
        if category in {item.casefold() for item in profile.projection.excluded_categories}:
            excluded += 1
            issues.append(
                _issue(
                    "EXERCISE_CATEGORY_EXCLUDED",
                    source_id or index,
                    "category",
                    observed=category,
                    severity="info",
                )
            )
            continue
        exercise_type = profile.projection.category_map.get(category)
        primary = _unique_text((values.get("primary_muscle"),))
        if not source_id or not upstream_name or not exercise_type or not primary:
            rejected += 1
            issues.append(
                _issue(
                    "CANONICAL_RECORD_INVALID",
                    source_id or index,
                    "exercise",
                    observed={"category": category, "primaryMuscles": primary},
                )
            )
            continue
        enrichment = enrichments.get(source_id)
        if enrichment:
            enriched += 1
            name = enrichment["name_zh"]
            aliases = _unique_text(
                (upstream_name, *enrichment["aliases"], *enrichment["pinyin"])
            )
        else:
            name = upstream_name
            aliases = ()
            issues.append(
                _issue(
                    "ENRICHMENT_ENGLISH_FALLBACK",
                    source_id,
                    "name",
                    severity="info",
                )
            )
        records.append(
            CanonicalExerciseRecord(
                source_name=profile.source_name,
                source_record_id=source_id,
                dataset_version=profile.dataset_version,
                license=profile.license,
                attribution=profile.attribution,
                name=name,
                exercise_type=exercise_type,
                primary_muscle=primary[0],
                secondary_muscles=_unique_text(values.get("secondary_muscles") or []),
                aliases=aliases,
                provenance={
                    "profile": f"{profile.profile_name}@{profile.profile_version}",
                    "upstream_name": upstream_name,
                    "original_category": category,
                    "equipment": values.get("equipment"),
                    "level": values.get("level"),
                    "mechanic": values.get("mechanic"),
                    "force": values.get("force"),
                    "instructions": values.get("instructions"),
                    "image_count": len(values.get("images") or []),
                },
            )
        )
    compatible_count = len(records)
    coverage = enriched / compatible_count if compatible_count else 0
    return ProjectionResult(
        catalog_kind="exercise",
        records=tuple(records),
        issues=tuple(issues),
        scanned_count=len(raw_records),
        excluded_count=excluded,
        rejected_count=rejected,
        enrichment_count=enriched,
        enrichment_coverage=coverage,
    )


def _load_enrichment(path: str | Path) -> dict[str, dict[str, Any]]:
    try:
        pairs = json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=_pairs_without_duplicates,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ReceiverError(
            "ENRICHMENT_INVALID",
            f"Exercise enrichment is invalid: {Path(path).name}",
            exit_code=4,
        ) from error
    if not isinstance(pairs, dict):
        raise ReceiverError("ENRICHMENT_INVALID", "Exercise enrichment must be an object.", exit_code=4)
    result: dict[str, dict[str, Any]] = {}
    seen_names: set[str] = set()
    for source_id, value in pairs.items():
        if not isinstance(source_id, str) or not source_id.strip() or not isinstance(value, dict):
            raise ReceiverError("ENRICHMENT_INVALID", "Enrichment identities must map to objects.", exit_code=4)
        name = value.get("name_zh")
        aliases = value.get("aliases", [])
        pinyin = value.get("pinyin", [])
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(aliases, list)
            or not isinstance(pinyin, list)
            or any(not isinstance(item, str) or not item.strip() for item in [*aliases, *pinyin])
            or any(not re.fullmatch(r"[a-z0-9 -]+", item.casefold()) for item in pinyin)
        ):
            raise ReceiverError("ENRICHMENT_INVALID", f"Invalid enrichment for {source_id}.", exit_code=4)
        raw_values = [_text(item).casefold() for item in (name, *aliases)]
        if len(set(raw_values)) != len(raw_values):
            raise ReceiverError(
                "ENRICHMENT_ALIAS_DUPLICATE",
                f"Duplicate alias within enrichment for {source_id}.",
                exit_code=4,
            )
        normalized_values = set(raw_values)
        if seen_names & normalized_values:
            raise ReceiverError("ENRICHMENT_ALIAS_DUPLICATE", f"Duplicate enrichment name for {source_id}.", exit_code=4)
        seen_names.update(normalized_values)
        result[source_id.strip()] = {
            "name_zh": name.strip(),
            "aliases": _unique_text(aliases),
            "pinyin": _unique_text(pinyin),
        }
    return result


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


def _issue(
    code: str,
    record: int | str,
    field: str | None,
    *,
    observed: Any = None,
    expected: str | None = None,
    severity: str = "error",
) -> ReceiverIssue:
    return ReceiverIssue(
        severity=severity,
        code=code,
        record=record,
        source_path=f"records[{record}]",
        field=field,
        observed=observed,
        expected=expected,
    )


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _unique_text(values: Iterable[Any]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        text = value.strip()
        key = text.casefold()
        if key not in seen:
            result.append(text)
            seen.add(key)
    return tuple(result)
