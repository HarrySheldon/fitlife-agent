from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.catalog_receiver.models import CsvSource, JsonSource, ReceiverError
from backend.catalog_receiver.readers import read_source


def test_reads_utf8_bom_csv_with_quoted_embedded_newline(tmp_path: Path) -> None:
    path = tmp_path / "foods.csv"
    path.write_bytes(b'\xef\xbb\xbfid,name\r\n1,"rice\nwhite"\r\n')

    source = read_source(path)

    assert isinstance(source, CsvSource)
    assert source.headers == ("id", "name")
    assert source.rows == ({"id": "1", "name": "rice\nwhite"},)
    assert source.metadata.basename == "foods.csv"
    assert len(source.metadata.sha256) == 64


def test_reads_json_root_array(tmp_path: Path) -> None:
    path = tmp_path / "exercises.json"
    path.write_text(json.dumps([{"id": "squat"}]), encoding="utf-8")

    source = read_source(path)

    assert isinstance(source, JsonSource)
    assert source.document == [{"id": "squat"}]


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("https://example.com/foods.csv", "SOURCE_URL_UNSUPPORTED"),
        ("missing.csv", "SOURCE_NOT_FOUND"),
    ],
)
def test_rejects_non_local_sources(tmp_path: Path, value: str, code: str) -> None:
    with pytest.raises(ReceiverError) as raised:
        read_source(tmp_path / value if value == "missing.csv" else value)

    assert raised.value.code == code


def test_rejects_directory_and_unsupported_extension(tmp_path: Path) -> None:
    with pytest.raises(ReceiverError) as directory:
        read_source(tmp_path)
    assert directory.value.code == "SOURCE_NOT_FILE"

    path = tmp_path / "foods.xlsx"
    path.write_bytes(b"data")
    with pytest.raises(ReceiverError) as extension:
        read_source(path)
    assert extension.value.code == "SOURCE_EXTENSION_UNSUPPORTED"
    assert ".csv" in extension.value.message
    assert ".json" in extension.value.message


def test_rejects_duplicate_headers(tmp_path: Path) -> None:
    path = tmp_path / "foods.csv"
    path.write_text("name,Name\nrice,rice\n", encoding="utf-8")

    with pytest.raises(ReceiverError) as raised:
        read_source(path)

    assert raised.value.code == "CSV_HEADERS_DUPLICATE"


def test_rejects_invalid_utf8(tmp_path: Path) -> None:
    path = tmp_path / "foods.csv"
    path.write_bytes(b"name\n\xff\n")

    with pytest.raises(ReceiverError) as raised:
        read_source(path)

    assert raised.value.code == "SOURCE_ENCODING_INVALID"


def test_rejects_malformed_and_oversized_json(tmp_path: Path) -> None:
    malformed = tmp_path / "bad.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(ReceiverError) as syntax:
        read_source(malformed)
    assert syntax.value.code == "JSON_INVALID"

    large = tmp_path / "large.json"
    large.write_text('["123456"]', encoding="utf-8")
    with pytest.raises(ReceiverError) as size:
        read_source(large, json_size_limit=5)
    assert size.value.code == "JSON_SIZE_LIMIT_EXCEEDED"


def test_configured_delimiter_handles_single_column_samples(tmp_path: Path) -> None:
    path = tmp_path / "foods.csv"
    path.write_text("name\nrice\n", encoding="utf-8")

    source = read_source(path, csv_delimiter=",")

    assert isinstance(source, CsvSource)
    assert source.rows == ({"name": "rice"},)
