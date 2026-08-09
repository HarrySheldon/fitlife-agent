from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from urllib.parse import urlparse

from backend.catalog_receiver.models import (
    CsvDialectInfo,
    CsvSource,
    JsonSource,
    ReceiverError,
    SourceDocument,
    SourceMetadata,
)


DEFAULT_JSON_SIZE_LIMIT = 100_000_000
SUPPORTED_EXTENSIONS = (".csv", ".json")


def read_source(
    path: str | Path,
    *,
    json_size_limit: int = DEFAULT_JSON_SIZE_LIMIT,
    csv_delimiter: str | None = None,
) -> SourceDocument:
    raw_path = str(path)
    parsed = urlparse(raw_path)
    if parsed.scheme and (parsed.netloc or parsed.scheme in {"http", "https", "ftp"}):
        raise ReceiverError(
            "SOURCE_URL_UNSUPPORTED",
            "Only local CSV and JSON files are accepted.",
        )

    source_path = Path(path).expanduser()
    if not source_path.exists():
        raise ReceiverError("SOURCE_NOT_FOUND", f"Source file not found: {source_path.name}")
    if not source_path.is_file():
        raise ReceiverError("SOURCE_NOT_FILE", "The source path must be a file.")

    suffix = source_path.suffix.casefold()
    if suffix not in SUPPORTED_EXTENSIONS:
        accepted = ", ".join(SUPPORTED_EXTENSIONS)
        raise ReceiverError(
            "SOURCE_EXTENSION_UNSUPPORTED",
            f"Unsupported source extension. Accepted extensions: {accepted}.",
        )

    stat = source_path.stat()
    if suffix == ".json" and stat.st_size > json_size_limit:
        raise ReceiverError(
            "JSON_SIZE_LIMIT_EXCEEDED",
            f"JSON source exceeds the {json_size_limit}-byte limit.",
        )

    digest = _sha256(source_path)
    metadata = SourceMetadata(
        basename=source_path.name,
        kind="csv" if suffix == ".csv" else "json",
        size_bytes=stat.st_size,
        modified_at=stat.st_mtime,
        sha256=digest,
        encoding="utf-8-sig",
    )
    if suffix == ".csv":
        return _read_csv(source_path, metadata, delimiter=csv_delimiter)
    return _read_json(source_path, metadata)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise ReceiverError(
            "SOURCE_ENCODING_INVALID",
            "Source must be valid UTF-8 or UTF-8 with BOM.",
        ) from error


def _read_csv(
    path: Path,
    metadata: SourceMetadata,
    *,
    delimiter: str | None,
) -> CsvSource:
    text = _read_text(path)
    sample = text[:65536]
    try:
        dialect = (
            _configured_dialect(delimiter)
            if delimiter is not None
            else csv.Sniffer().sniff(sample, delimiters=",;\t|")
        )
    except csv.Error as error:
        raise ReceiverError(
            "CSV_DIALECT_AMBIGUOUS",
            "CSV dialect could not be determined; configure a delimiter explicitly.",
        ) from error

    reader = csv.reader(io.StringIO(text, newline=""), dialect=dialect)
    try:
        raw_headers = next(reader)
    except StopIteration as error:
        raise ReceiverError("CSV_HEADERS_MISSING", "CSV source has no header row.") from error
    headers = tuple(header.strip() for header in raw_headers)
    if not headers or any(not header for header in headers):
        raise ReceiverError("CSV_HEADERS_INVALID", "CSV headers must be non-empty.")
    normalized = [header.casefold() for header in headers]
    if len(set(normalized)) != len(normalized):
        raise ReceiverError("CSV_HEADERS_DUPLICATE", "CSV headers must be unique.")

    rows: list[dict[str, str]] = []
    for row_number, values in enumerate(reader, start=2):
        if not values or all(not value.strip() for value in values):
            continue
        if len(values) != len(headers):
            raise ReceiverError(
                "CSV_ROW_WIDTH_INVALID",
                f"CSV row {row_number} has {len(values)} values; expected {len(headers)}.",
            )
        rows.append(dict(zip(headers, values, strict=True)))
    dialect_info = CsvDialectInfo(
        delimiter=dialect.delimiter,
        quotechar=dialect.quotechar,
        doublequote=dialect.doublequote,
        escapechar=dialect.escapechar,
        lineterminator=getattr(dialect, "lineterminator", "\n"),
    )
    return CsvSource(
        metadata=metadata,
        headers=headers,
        rows=tuple(rows),
        dialect=dialect_info,
    )


def _configured_dialect(delimiter: str) -> type[csv.Dialect]:
    if len(delimiter) != 1:
        raise ReceiverError(
            "CSV_DELIMITER_INVALID",
            "Configured CSV delimiter must be one character.",
        )

    class ConfiguredDialect(csv.excel):
        pass

    ConfiguredDialect.delimiter = delimiter
    return ConfiguredDialect


def _read_json(path: Path, metadata: SourceMetadata) -> JsonSource:
    text = _read_text(path)
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise ReceiverError(
            "JSON_INVALID",
            f"Malformed JSON at line {error.lineno}, column {error.colno}.",
        ) from error
    return JsonSource(metadata=metadata, document=document)
