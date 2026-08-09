from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from backend.catalog_receiver.models import (
    CatalogKind,
    CsvSource,
    FieldDescription,
    JsonSource,
    SourceDocument,
    StructureInspection,
)


_ALIASES: dict[CatalogKind, dict[str, tuple[str, ...]]] = {
    "food": {
        "source_record_id": ("id", "food_id", "source_record_id", "整合編號"),
        "name": ("name", "food_name", "樣品名稱"),
        "calories": ("calories", "energy", "熱量", "修正熱量"),
        "carbs": ("carbs", "carbohydrate", "總碳水化合物"),
        "protein": ("protein", "粗蛋白"),
        "fat": ("fat", "粗脂肪"),
    },
    "exercise": {
        "source_record_id": ("id", "exercise_id", "source_record_id"),
        "name": ("name", "exercise_name"),
        "exercise_type": ("category", "exercise_type", "type"),
        "primary_muscle": ("primaryMuscles", "primary_muscle", "muscle"),
    },
}


def inspect_structure(
    source: SourceDocument,
    *,
    catalog_kind: CatalogKind = "food",
    sample_limit: int = 5,
) -> StructureInspection:
    if isinstance(source, CsvSource):
        field_samples = {
            header: _unique(row[header] for row in source.rows)[:sample_limit]
            for header in source.headers
        }
        fields = tuple(
            FieldDescription(
                path=header,
                types=tuple(sorted({_type_name(item) for item in samples})),
                samples=tuple(samples),
            )
            for header, samples in field_samples.items()
        )
        paths = source.headers
        row_count = len(source.rows)
        arrays: tuple[str, ...] = ()
        candidates: tuple[str, ...] = ()
    else:
        discovered, discovered_arrays = _walk_json(source.document)
        fields = tuple(
            FieldDescription(
                path=path,
                types=tuple(sorted(types)),
                samples=tuple(samples[:sample_limit]),
            )
            for path, (types, samples) in sorted(discovered.items())
        )
        paths = tuple(item.path for item in fields)
        row_count = None
        arrays = tuple(sorted(discovered_arrays))
        candidates = tuple(
            path
            for path in arrays
            if _array_contains_objects(source.document, path)
        )
    mapped, ambiguous, missing = _mapping_candidates(paths, catalog_kind)
    draft = {
        "schema_version": 1,
        "catalog_kind": catalog_kind,
        "input_format": source.metadata.kind,
        "projection": {
            "strategy": "row",
            "record_selector": candidates[0] if len(candidates) == 1 else None,
            "fields": {
                field: {"selector": selector}
                for field, selector in mapped.items()
            },
            "unresolved_fields": [*missing, *ambiguous],
        },
    }
    return StructureInspection(
        source=source.metadata,
        row_count=row_count,
        headers=source.headers if isinstance(source, CsvSource) else (),
        array_paths=arrays,
        candidate_record_arrays=candidates,
        fields=fields,
        mapping_candidates=mapped,
        ambiguous_fields=ambiguous,
        missing_fields=missing,
        draft_profile=draft,
    )


def _mapping_candidates(
    paths: Iterable[str],
    catalog_kind: CatalogKind,
) -> tuple[dict[str, str], dict[str, tuple[str, ...]], tuple[str, ...]]:
    by_leaf: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        leaf = path.rsplit(".", 1)[-1].replace("[]", "").casefold()
        by_leaf[leaf].append(path)
    mapped: dict[str, str] = {}
    ambiguous: dict[str, tuple[str, ...]] = {}
    missing: list[str] = []
    for canonical, aliases in _ALIASES[catalog_kind].items():
        matches = {
            path
            for alias in aliases
            for path in by_leaf.get(alias.casefold(), [])
        }
        if len(matches) == 1:
            mapped[canonical] = next(iter(matches))
        elif len(matches) > 1:
            ambiguous[canonical] = tuple(sorted(matches))
        else:
            missing.append(canonical)
    return mapped, ambiguous, tuple(missing)


def _walk_json(document: Any) -> tuple[dict[str, tuple[set[str], list[Any]]], set[str]]:
    fields: dict[str, tuple[set[str], list[Any]]] = {}
    arrays: set[str] = set()

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else str(key)
                visit(child, child_path)
        elif isinstance(value, list):
            array_path = f"{path}[]" if path else "[]"
            arrays.add(path or "@")
            for child in value[:100]:
                visit(child, array_path)
        elif path:
            types, samples = fields.setdefault(path, (set(), []))
            types.add(_type_name(value))
            if value not in samples and len(samples) < 5:
                samples.append(value)

    visit(document, "")
    return fields, arrays


def _array_contains_objects(document: Any, path: str) -> bool:
    if path == "@":
        values = [document]
    else:
        values: list[Any] = [document]
        for part in path.split("."):
            next_values: list[Any] = []
            flatten = part.endswith("[]")
            key = part[:-2] if flatten else part
            for value in values:
                child = value.get(key) if isinstance(value, dict) else None
                if flatten and isinstance(child, list):
                    next_values.extend(child)
                elif child is not None:
                    next_values.append(child)
            values = next_values
    return any(
        isinstance(value, list) and bool(value) and isinstance(value[0], dict)
        for value in values
    )


def _unique(values: Iterable[Any]) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__
