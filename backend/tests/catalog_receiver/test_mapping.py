from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.catalog_receiver.mapping import (
    apply_transform,
    load_mapping_profile,
    resolve_field,
    select_value,
)
from backend.catalog_receiver.models import FieldSpec, ReceiverError, TransformSpec


def test_applies_allow_listed_transforms() -> None:
    assert apply_transform("  Foo  ", TransformSpec(operation="strip")) == "Foo"
    assert apply_transform("1,234.5", TransformSpec(operation="number")) == 1234.5
    assert apply_transform([None, "x"], TransformSpec(operation="first")) == "x"
    assert apply_transform("x", TransformSpec(operation="list")) == ["x"]
    assert apply_transform("x", TransformSpec(operation="constant", value="fixed")) == "fixed"
    assert apply_transform(
        "CARDIO",
        TransformSpec(operation="enum_map", values={"cardio": "cardio"}),
    ) == "cardio"
    assert apply_transform("總碳水化合物", TransformSpec(operation="opencc_t2s")) == "总碳水化合物"
    assert apply_transform("CARDIO", TransformSpec(operation="lower")) == "cardio"


def test_resolves_jmespath_field_and_rejects_bad_selector() -> None:
    field = FieldSpec(
        selector="nutrients.protein",
        transforms=(TransformSpec(operation="number"),),
    )
    assert resolve_field({"nutrients": {"protein": "12"}}, field) == 12

    with pytest.raises(ReceiverError) as raised:
        select_value({}, "[")
    assert raised.value.code == "MAPPING_SELECTOR_INVALID"


def test_profile_forbids_unknown_or_executable_fields(tmp_path: Path) -> None:
    profile = {
        "schema_version": 1,
        "profile_name": "bad",
        "profile_version": "1",
        "catalog_kind": "food",
        "input_format": "json",
        "source_name": "source",
        "dataset_version": "1",
        "license": "license",
        "attribution": "attribution",
        "projection": {
            "strategy": "row",
            "fields": {"name": {"selector": "name", "expression": "__import__('os')"}},
        },
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(profile), encoding="utf-8")

    with pytest.raises(ReceiverError) as raised:
        load_mapping_profile(path)

    assert raised.value.code == "MAPPING_PROFILE_INVALID"
    assert raised.value.exit_code == 3


def test_transform_model_rejects_unknown_operation() -> None:
    with pytest.raises(ValidationError):
        TransformSpec.model_validate({"operation": "python", "value": "print(1)"})
