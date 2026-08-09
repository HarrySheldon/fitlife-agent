from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Protocol

from backend.catalog_receiver.inspector import inspect_structure
from backend.catalog_receiver.mapping import load_mapping_profile
from backend.catalog_receiver.models import (
    CanonicalRecord,
    CatalogKind,
    MappingProfile,
    ReceiverError,
    ReceiverIssue,
    ReceiverResult,
    StructureInspection,
)
from backend.catalog_receiver.projectors import project_source
from backend.catalog_receiver.readers import read_source
from backend.catalog_receiver.reporting import build_report, write_run_artifacts
from backend.catalog_receiver.validators import validate_records


class CatalogSink(Protocol):
    def import_records(
        self,
        profile: MappingProfile,
        records: tuple[CanonicalRecord, ...],
    ) -> dict[str, object]: ...


class CatalogReceiver:
    def __init__(self, sink: CatalogSink | None = None) -> None:
        self._sink = sink

    def inspect(
        self,
        path: str | Path,
        *,
        catalog_kind: CatalogKind = "food",
        json_size_limit: int = 100_000_000,
        csv_delimiter: str | None = None,
    ) -> StructureInspection:
        source = read_source(
            path,
            json_size_limit=json_size_limit,
            csv_delimiter=csv_delimiter,
        )
        return inspect_structure(source, catalog_kind=catalog_kind)

    def validate(
        self,
        path: str | Path,
        *,
        mapping: str | Path | MappingProfile,
        enrichment_path: str | Path | None = None,
        output_dir: str | Path | None = None,
        json_size_limit: int = 100_000_000,
        csv_delimiter: str | None = None,
    ) -> ReceiverResult:
        return self._run(
            path,
            mapping=mapping,
            enrichment_path=enrichment_path,
            output_dir=output_dir,
            json_size_limit=json_size_limit,
            csv_delimiter=csv_delimiter,
            import_records=False,
        )

    def import_catalog(
        self,
        path: str | Path,
        *,
        mapping: str | Path | MappingProfile,
        enrichment_path: str | Path | None = None,
        output_dir: str | Path | None = None,
        json_size_limit: int = 100_000_000,
        csv_delimiter: str | None = None,
    ) -> ReceiverResult:
        if self._sink is None:
            raise ReceiverError(
                "DATABASE_SINK_REQUIRED",
                "A database sink is required for import.",
                exit_code=5,
            )
        return self._run(
            path,
            mapping=mapping,
            enrichment_path=enrichment_path,
            output_dir=output_dir,
            json_size_limit=json_size_limit,
            csv_delimiter=csv_delimiter,
            import_records=True,
        )

    def _run(
        self,
        path: str | Path,
        *,
        mapping: str | Path | MappingProfile,
        enrichment_path: str | Path | None,
        output_dir: str | Path | None,
        json_size_limit: int,
        csv_delimiter: str | None,
        import_records: bool,
    ) -> ReceiverResult:
        started = perf_counter()
        profile = mapping if isinstance(mapping, MappingProfile) else load_mapping_profile(mapping)
        source = read_source(
            path,
            json_size_limit=json_size_limit,
            csv_delimiter=csv_delimiter,
        )
        projection = project_source(source, profile, enrichment_path=enrichment_path)
        validation_issues = validate_records(projection.records)
        if not projection.records:
            validation_issues = (
                *validation_issues,
                ReceiverIssue(
                    severity="error",
                    code="NO_RECORDS_ACCEPTED",
                    source_path=source.metadata.basename,
                    expected="at least one complete canonical record",
                ),
            )
        preliminary = build_report(
            source=source.metadata,
            profile=profile,
            projection=projection,
            validation_issues=validation_issues,
            duration_ms=int((perf_counter() - started) * 1_000),
        )
        transaction = None
        if import_records:
            if preliminary.has_errors:
                transaction = {"status": "blocked", "reason": "validation_errors"}
            else:
                assert self._sink is not None
                try:
                    transaction = self._sink.import_records(profile, projection.records)
                except ReceiverError:
                    raise
                except Exception as error:
                    raise ReceiverError(
                        "DATABASE_IMPORT_FAILED",
                        "Catalog database import failed.",
                        exit_code=5,
                    ) from error
        report = build_report(
            source=source.metadata,
            profile=profile,
            projection=projection,
            validation_issues=validation_issues,
            duration_ms=int((perf_counter() - started) * 1_000),
            transaction=transaction,
        )
        result = ReceiverResult(report=report, records=projection.records)
        if output_dir is not None:
            write_run_artifacts(output_dir, report, projection.records)
        return result
