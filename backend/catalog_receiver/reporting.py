from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from backend.catalog_receiver.models import (
    CanonicalExerciseRecord,
    CanonicalFoodRecord,
    CanonicalRecord,
    MappingProfile,
    ProjectionResult,
    ReceiverIssue,
    ReceiverReport,
    SourceMetadata,
)
from backend.catalog_receiver.validators import enrich_issue


MAX_ISSUE_DETAILS = 1_000


def build_report(
    *,
    source: SourceMetadata,
    profile: MappingProfile,
    projection: ProjectionResult,
    validation_issues: Iterable[ReceiverIssue] = (),
    duration_ms: int = 0,
    transaction: dict[str, Any] | None = None,
) -> ReceiverReport:
    all_issues = tuple(
        enrich_issue(issue)
        for issue in (*projection.issues, *tuple(validation_issues))
    )
    counts = Counter(issue.code for issue in all_issues)
    has_errors = any(issue.severity == "error" for issue in all_issues)
    model = CanonicalFoodRecord if profile.catalog_kind == "food" else CanonicalExerciseRecord
    return ReceiverReport(
        source=source,
        catalog_kind=profile.catalog_kind,
        profile_name=profile.profile_name,
        profile_version=profile.profile_version,
        source_name=profile.source_name,
        dataset_version=profile.dataset_version,
        scanned_count=projection.scanned_count,
        accepted_count=len(projection.records),
        excluded_count=projection.excluded_count,
        rejected_count=projection.rejected_count,
        enrichment_count=projection.enrichment_count,
        enrichment_coverage=projection.enrichment_coverage,
        issue_counts=dict(sorted(counts.items())),
        total_issue_count=len(all_issues),
        error_count=sum(issue.severity == "error" for issue in all_issues),
        warning_count=sum(issue.severity == "warning" for issue in all_issues),
        info_count=sum(issue.severity == "info" for issue in all_issues),
        issues_truncated=len(all_issues) > MAX_ISSUE_DETAILS,
        issues=all_issues[:MAX_ISSUE_DETAILS],
        canonical_schema=model.model_json_schema() if has_errors else None,
        canonical_example=_canonical_example(profile.catalog_kind) if has_errors else None,
        transaction=transaction,
        duration_ms=duration_ms,
    )


def write_run_artifacts(
    output_dir: str | Path,
    report: ReceiverReport,
    records: tuple[CanonicalRecord, ...],
) -> None:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    _atomic_json(directory / "catalog-import-report.json", report.model_dump(mode="json"))
    _atomic_text(directory / "catalog-import-report.txt", render_text_report(report))
    if not report.has_errors:
        name = "normalized-foods.json" if report.catalog_kind == "food" else "normalized-exercises.json"
        _atomic_json(
            directory / name,
            {
                "catalog_kind": report.catalog_kind,
                "source_name": report.source_name,
                "dataset_version": report.dataset_version,
                "records": [record.model_dump(mode="json") for record in records],
            },
        )


def render_text_report(report: ReceiverReport) -> str:
    status = "blocked" if report.has_errors else "valid"
    lines = [
        f"Catalog import report: {status}",
        f"Source: {report.source.basename}",
        f"Profile: {report.profile_name}@{report.profile_version}",
        f"Scanned: {report.scanned_count}",
        f"Accepted: {report.accepted_count}",
        f"Excluded: {report.excluded_count}",
        f"Rejected: {report.rejected_count}",
        f"Issues: {report.total_issue_count}",
    ]
    for code, count in report.issue_counts.items():
        lines.append(f"  {code}: {count}")
    if report.issues_truncated:
        lines.append(f"Details truncated to {MAX_ISSUE_DETAILS} issues.")
    return "\n".join(lines) + "\n"


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _atomic_text(path: Path, value: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def _canonical_example(catalog_kind: str) -> dict[str, Any]:
    if catalog_kind == "food":
        return {
            "source_name": "example-source",
            "source_record_id": "food-1",
            "dataset_version": "2026-01-01",
            "license": "license name",
            "attribution": "source owner",
            "name": "米饭",
            "basis_type": "per_100g",
            "basis_amount": 100,
            "unit": "g",
            "calories": 130,
            "carbs": 28.2,
            "protein": 2.7,
            "fat": 0.3,
            "aliases": ["白飯"],
            "provenance": {"profile": "example@1"},
        }
    return {
        "source_name": "example-source",
        "source_record_id": "exercise-1",
        "dataset_version": "2026-01-01",
        "license": "license name",
        "attribution": "source owner",
        "name": "深蹲",
        "exercise_type": "strength",
        "primary_muscle": "quadriceps",
        "secondary_muscles": ["glutes"],
        "met": None,
        "aliases": ["squat"],
        "provenance": {"profile": "example@1"},
    }
