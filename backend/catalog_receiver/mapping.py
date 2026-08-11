from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import jmespath
from opencc import OpenCC
from pydantic import ValidationError

from backend.catalog_receiver.models import (
    FieldSpec,
    MappingProfile,
    ReceiverError,
    TransformSpec,
)


_T2S = OpenCC("t2s")
_TW2SP = OpenCC("tw2sp")
_MAINLAND_FOOD_GLOSSARY = (
    ("白饭", "米饭"),
    ("鲔鱼", "金枪鱼"),
    ("马铃薯", "土豆"),
    ("青花菜", "西兰花"),
    ("奇异果", "猕猴桃"),
    ("凤梨", "菠萝"),
)


def load_mapping_profile(path: str | Path) -> MappingProfile:
    profile_path = Path(path)
    try:
        raw = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReceiverError(
            "MAPPING_PROFILE_INVALID",
            f"Mapping profile could not be read: {profile_path.name}",
            exit_code=3,
        ) from error
    try:
        return MappingProfile.model_validate(raw)
    except ValidationError as error:
        raise ReceiverError(
            "MAPPING_PROFILE_INVALID",
            f"Mapping profile is invalid: {error.errors(include_url=False)}",
            exit_code=3,
        ) from error


def select_value(record: Any, selector: str) -> Any:
    if isinstance(record, dict) and selector in record:
        return record[selector]
    try:
        return jmespath.search(selector, record)
    except (jmespath.exceptions.JMESPathError, TypeError) as error:
        raise ReceiverError(
            "MAPPING_SELECTOR_INVALID",
            f"Invalid JMESPath selector: {selector}",
            exit_code=3,
        ) from error


def resolve_field(record: Any, spec: FieldSpec) -> Any:
    value = spec.constant if spec.selector is None else select_value(record, spec.selector)
    for transform in spec.transforms:
        value = apply_transform(value, transform)
    return value


def apply_transform(value: Any, transform: TransformSpec) -> Any:
    operation = transform.operation
    if operation == "strip":
        return value.strip() if isinstance(value, str) else value
    if operation == "number":
        return _number(value)
    if operation == "first":
        if isinstance(value, (list, tuple)):
            return next((item for item in value if item not in (None, "")), None)
        return value
    if operation == "list":
        if value is None:
            return []
        return list(value) if isinstance(value, (list, tuple, set)) else [value]
    if operation == "constant":
        return transform.value
    if operation == "enum_map":
        assert transform.values is not None
        key = str(value).strip().casefold()
        normalized = {str(item).casefold(): result for item, result in transform.values.items()}
        return normalized.get(key)
    if operation == "opencc_t2s":
        return convert_t2s(value) if isinstance(value, str) else value
    if operation == "opencc_tw2sp":
        return convert_tw2sp(value)[0] if isinstance(value, str) else value
    if operation == "lower":
        return value.casefold() if isinstance(value, str) else value
    raise ReceiverError(
        "MAPPING_TRANSFORM_UNSUPPORTED",
        f"Unsupported transform: {operation}",
        exit_code=3,
    )


def convert_tw2sp(value: str) -> tuple[str, bool]:
    converted = convert_tw2sp_base(value)
    localized = converted
    for taiwan_term, mainland_term in _MAINLAND_FOOD_GLOSSARY:
        localized = localized.replace(taiwan_term, mainland_term)
    return localized, localized != converted


def convert_tw2sp_base(value: str) -> str:
    return _TW2SP.convert(value)


def convert_t2s(value: str) -> str:
    return _T2S.convert(value)


def _number(value: Any) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError) as error:
        raise ReceiverError(
            "VALUE_NUMBER_INVALID",
            f"Value is not numeric: {value!r}",
            exit_code=4,
        ) from error
    if not math.isfinite(number):
        raise ReceiverError(
            "VALUE_NUMBER_INVALID",
            "Numeric values must be finite.",
            exit_code=4,
        )
    return number
