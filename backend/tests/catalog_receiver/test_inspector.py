from __future__ import annotations

import json
from pathlib import Path

from backend.catalog_receiver.inspector import inspect_structure
from backend.catalog_receiver.readers import read_source


def test_inspects_csv_and_proposes_only_unique_fields(tmp_path: Path) -> None:
    path = tmp_path / "foods.csv"
    path.write_text(
        "id,name,calories,carbs,protein,fat\n1,Rice,130,28,2.7,0.3\n",
        encoding="utf-8",
    )

    result = inspect_structure(read_source(path), catalog_kind="food")

    assert result.row_count == 1
    assert result.headers[0] == "id"
    assert result.mapping_candidates["name"] == "name"
    assert result.missing_fields == ()


def test_reports_ambiguous_json_fields_without_guessing(tmp_path: Path) -> None:
    path = tmp_path / "foods.json"
    path.write_text(
        json.dumps({"foods": [{"id": "1", "name": "Rice", "nested": {"name": "Other"}}]}),
        encoding="utf-8",
    )

    result = inspect_structure(read_source(path), catalog_kind="food")

    assert result.candidate_record_arrays == ("foods",)
    assert result.ambiguous_fields["name"] == (
        "foods[].name",
        "foods[].nested.name",
    )
    assert "name" in result.draft_profile["projection"]["unresolved_fields"]
    assert "name" not in result.draft_profile["projection"]["fields"]


def test_discovers_nested_record_arrays(tmp_path: Path) -> None:
    path = tmp_path / "exercise.json"
    path.write_text(
        json.dumps({"data": {"exercises": [{"id": "squat", "name": "Squat"}]}}),
        encoding="utf-8",
    )

    result = inspect_structure(read_source(path), catalog_kind="exercise")

    assert "data.exercises" in result.array_paths
    assert result.candidate_record_arrays == ("data.exercises",)


def test_discovers_record_arrays_nested_inside_arrays(tmp_path: Path) -> None:
    path = tmp_path / "nested.json"
    path.write_text(
        json.dumps({"groups": [{"items": [{"id": "one", "name": "One"}]}]}),
        encoding="utf-8",
    )

    result = inspect_structure(read_source(path), catalog_kind="exercise")

    assert "groups[].items" in result.array_paths
    assert "groups[].items" in result.candidate_record_arrays
