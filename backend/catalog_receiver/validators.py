from __future__ import annotations

from collections import Counter
from typing import Iterable

from backend.catalog_receiver.models import (
    CanonicalExerciseRecord,
    CanonicalFoodRecord,
    CanonicalRecord,
    ReceiverIssue,
)


ISSUE_MESSAGES: dict[str, tuple[str, str | None]] = {
    "REQUIRED_VALUE_MISSING": ("A required source value is missing.", "Map a non-empty source field."),
    "REQUIRED_NUTRIENT_MISSING": ("A required nutrient is missing.", "Provide calories, carbohydrate, protein, and fat per 100 g."),
    "GROUP_DESCRIPTOR_INCONSISTENT": ("Rows in one source group disagree.", "Use one stable descriptor per grouped identity."),
    "NUTRIENT_DUPLICATE": ("A grouped nutrient occurs more than once.", "Remove duplicate nutrient rows or select one explicitly."),
    "NUTRIENT_UNIT_UNSUPPORTED": ("The nutrient unit is unsupported.", "Use kcal for calories and g for macronutrients."),
    "VALUE_NUMBER_INVALID": ("A numeric source value is missing or invalid.", "Provide a finite non-negative number."),
    "CANONICAL_RECORD_INVALID": ("The projected canonical record is invalid.", "Correct the mapped values using the canonical schema and example."),
    "CANONICAL_ID_DUPLICATE": ("The source identity is duplicated.", "Each source record ID must be unique."),
    "EXERCISE_CATEGORY_EXCLUDED": ("The exercise category is excluded by policy.", None),
    "ENRICHMENT_ENGLISH_FALLBACK": ("No reviewed Chinese enrichment exists; the English name is used.", None),
    "ENRICHMENT_ORPHAN": ("An enrichment identity does not exist upstream.", "Remove the orphan or correct its upstream ID."),
    "FOOD_GROUP_EXCLUDED_INCOMPLETE_NUTRITION": ("The food was excluded because one or more required nutrients are blank.", None),
    "LOCALIZATION_OVERRIDE_REVIEW_NOTE_MISSING": (
        "A record-specific food localization override lacks a review note.",
        "Add a non-empty review note explaining the override.",
    ),
    "LOCALIZATION_MISSING": (
        "A compatible exercise lacks complete Simplified Chinese localization.",
        "Add its stable source ID to the exercise overlay and complete every referenced taxonomy value.",
    ),
    "LOCALIZATION_INSTRUCTION_COUNT_MISMATCH": (
        "Localized exercise instructions do not match the upstream instruction count.",
        "Provide one localized instruction for each upstream instruction, in the same order.",
    ),
    "NO_RECORDS_ACCEPTED": ("No complete canonical records were accepted.", "Correct the mapping or source data before importing."),
}


def validate_records(records: Iterable[CanonicalRecord]) -> tuple[ReceiverIssue, ...]:
    records = tuple(records)
    counts = Counter((record.source_name, record.source_record_id) for record in records)
    issues: list[ReceiverIssue] = []
    for (source_name, source_id), count in counts.items():
        if count > 1:
            issues.append(
                ReceiverIssue(
                    severity="error",
                    code="CANONICAL_ID_DUPLICATE",
                    record=source_id,
                    source_path=source_name,
                    field="source_record_id",
                    observed=count,
                    expected="one record per source identity",
                )
            )
    for record in records:
        if isinstance(record, CanonicalFoodRecord):
            if record.basis_type != "per_100g" or record.basis_amount != 100 or record.unit != "g":
                issues.append(
                    ReceiverIssue(
                        severity="error",
                        code="FOOD_BASIS_INVALID",
                        record=record.source_record_id,
                        field="basis_type",
                        observed={
                            "basis_type": record.basis_type,
                            "basis_amount": record.basis_amount,
                            "unit": record.unit,
                        },
                        expected="per_100g, 100, g",
                    )
                )
        elif isinstance(record, CanonicalExerciseRecord) and not record.primary_muscle.strip():
            issues.append(
                ReceiverIssue(
                    severity="error",
                    code="EXERCISE_PRIMARY_MUSCLE_MISSING",
                    record=record.source_record_id,
                    field="primary_muscle",
                    expected="non-empty muscle name",
                )
            )
    return tuple(issues)


def enrich_issue(issue: ReceiverIssue) -> ReceiverIssue:
    message, suggestion = ISSUE_MESSAGES.get(
        issue.code,
        (issue.message or "Catalog receiver issue.", issue.suggestion),
    )
    return issue.model_copy(
        update={
            "message": issue.message or message,
            "suggestion": issue.suggestion or suggestion,
        }
    )
