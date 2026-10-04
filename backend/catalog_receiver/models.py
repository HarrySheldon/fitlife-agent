from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SourceKind = Literal["csv", "json"]
CatalogKind = Literal["food", "exercise"]
Severity = Literal["info", "warning", "error"]


class ReceiverIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Severity
    code: str
    record: int | str | None = None
    source_path: str | None = None
    field: str | None = None
    observed: Any = None
    expected: str | None = None
    suggestion: str | None = None
    message: str | None = None


class ReceiverError(Exception):
    """A coded receiver failure suitable for CLI exit-code translation."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        exit_code: int = 2,
        issue: ReceiverIssue | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.issue = issue


class SourceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    basename: str
    kind: SourceKind
    size_bytes: int = Field(ge=0)
    modified_at: datetime
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    encoding: str


class CsvDialectInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delimiter: str
    quotechar: str
    doublequote: bool
    escapechar: str | None = None
    lineterminator: str = "\n"


class CsvSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: SourceMetadata
    headers: tuple[str, ...]
    rows: tuple[dict[str, str], ...]
    dialect: CsvDialectInfo


class JsonSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: SourceMetadata
    document: Any


SourceDocument = CsvSource | JsonSource


TransformOperation = Literal[
    "strip",
    "number",
    "first",
    "list",
    "constant",
    "enum_map",
    "opencc_t2s",
    "opencc_tw2sp",
    "lower",
]


class TransformSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: TransformOperation
    value: Any = None
    values: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_parameters(self) -> "TransformSpec":
        if self.operation == "enum_map" and self.values is None:
            raise ValueError("enum_map requires values")
        if self.operation != "enum_map" and self.values is not None:
            raise ValueError("values is only valid for enum_map")
        if self.operation != "constant" and self.value is not None:
            raise ValueError("value is only valid for constant")
        return self


class FieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selector: str | None = None
    constant: Any = None
    transforms: tuple[TransformSpec, ...] = ()

    @model_validator(mode="after")
    def validate_source(self) -> "FieldSpec":
        has_selector = self.selector is not None
        has_constant = "constant" in self.model_fields_set
        if has_selector == has_constant:
            raise ValueError("exactly one of selector or constant is required")
        return self


class PivotSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key_selector: str
    value_selector: str
    unit_selector: str | None = None
    targets: dict[str, tuple[str, ...]]


class EnrichmentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_field: str
    minimum_coverage: float = Field(default=0, ge=0, le=1)


class ProjectionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: Literal["row", "grouped_pivot"]
    record_selector: str | None = None
    grouping_key: str | None = None
    fields: dict[str, FieldSpec]
    pivot: PivotSpec | None = None
    category_map: dict[str, str] = Field(default_factory=dict)
    excluded_categories: tuple[str, ...] = ()
    exclude_incomplete_groups: bool = False

    @model_validator(mode="after")
    def validate_strategy(self) -> "ProjectionSpec":
        if self.strategy == "grouped_pivot":
            if not self.grouping_key or self.pivot is None:
                raise ValueError("grouped_pivot requires grouping_key and pivot")
        elif self.grouping_key is not None or self.pivot is not None:
            raise ValueError("row projection cannot configure grouping or pivot")
        return self


class MappingProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    profile_name: str = Field(min_length=1)
    profile_version: str = Field(min_length=1)
    catalog_kind: CatalogKind
    input_format: SourceKind
    source_name: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    license: str = Field(min_length=1)
    attribution: str = Field(min_length=1)
    projection: ProjectionSpec
    enrichment: EnrichmentSpec | None = None
    retired_sources: tuple[str, ...] = ()


class FieldDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    types: tuple[str, ...]
    samples: tuple[Any, ...]


class StructureInspection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: SourceMetadata
    row_count: int | None = None
    headers: tuple[str, ...] = ()
    array_paths: tuple[str, ...] = ()
    candidate_record_arrays: tuple[str, ...] = ()
    fields: tuple[FieldDescription, ...] = ()
    mapping_candidates: dict[str, str] = Field(default_factory=dict)
    ambiguous_fields: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    missing_fields: tuple[str, ...] = ()
    draft_profile: dict[str, Any]


class CanonicalFoodRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    source_name: str
    source_record_id: str
    dataset_version: str
    license: str
    attribution: str
    name: str
    basis_type: Literal["per_100g"] = "per_100g"
    basis_amount: float = 100
    unit: Literal["g"] = "g"
    calories: float = Field(ge=0)
    carbs: float = Field(ge=0)
    protein: float = Field(ge=0)
    fat: float = Field(ge=0)
    aliases: tuple[str, ...] = ()
    provenance: dict[str, Any]


class CanonicalExerciseRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    source_name: str
    source_record_id: str
    dataset_version: str
    license: str
    attribution: str
    name: str
    exercise_type: Literal["strength", "cardio"]
    primary_muscle: str
    secondary_muscles: tuple[str, ...] = ()
    met: float | None = Field(default=None, gt=0)
    aliases: tuple[str, ...] = ()
    provenance: dict[str, Any]


CanonicalRecord = CanonicalFoodRecord | CanonicalExerciseRecord


class ProjectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    catalog_kind: CatalogKind
    records: tuple[CanonicalRecord, ...]
    issues: tuple[ReceiverIssue, ...] = ()
    scanned_count: int
    excluded_count: int = 0
    rejected_count: int = 0
    enrichment_count: int = 0
    enrichment_coverage: float = Field(default=0, ge=0, le=1)


class ReceiverReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: SourceMetadata
    catalog_kind: CatalogKind
    profile_name: str
    profile_version: str
    source_name: str
    dataset_version: str
    scanned_count: int
    accepted_count: int
    excluded_count: int
    rejected_count: int
    enrichment_count: int = 0
    enrichment_coverage: float = 0
    issue_counts: dict[str, int] = Field(default_factory=dict)
    total_issue_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    issues_truncated: bool = False
    issues: tuple[ReceiverIssue, ...] = ()
    canonical_schema: dict[str, Any] | None = None
    canonical_example: dict[str, Any] | None = None
    transaction: dict[str, Any] | None = None
    duration_ms: int = 0

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0


class ReceiverResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report: ReceiverReport
    records: tuple[CanonicalRecord, ...]
