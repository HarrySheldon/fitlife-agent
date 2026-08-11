from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.catalog_receiver.localization import (
    load_localization_bundle,
    validate_localization_coverage,
)
from backend.catalog_receiver.models import ReceiverError


FIXTURES = Path(__file__).parent / "fixtures"
FOOD_LOCALIZATION = FIXTURES / "food-localization.zh-CN.json"
EXERCISE_LOCALIZATION = FIXTURES / "exercise-localization.zh-CN.json"
EXERCISE_TAXONOMY = FIXTURES / "exercise-taxonomy.zh-CN.json"


def _localized_copy(tmp_path: Path, source: Path, update: dict[str, object]) -> Path:
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload.update(update)
    target = tmp_path / source.name
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return target


def test_loads_valid_food_asset_and_preserves_authored_aliases() -> None:
    bundle = load_localization_bundle(
        catalog_kind="food",
        localization_path=FOOD_LOCALIZATION,
    )

    localized = bundle.food("A001")

    assert localized.name_zh_cn == "米饭"
    assert localized.aliases == ("白飯", "Cooked rice")
    with pytest.raises(TypeError):
        bundle.food_entries["A003"] = localized  # type: ignore[index]


def test_loads_valid_exercise_and_taxonomy_assets() -> None:
    bundle = load_localization_bundle(
        catalog_kind="exercise",
        localization_path=EXERCISE_LOCALIZATION,
        taxonomy_path=EXERCISE_TAXONOMY,
    )

    localized = bundle.exercise("Barbell_Full_Squat", instruction_count=2)

    assert localized.name_zh_cn == "杠铃深蹲"
    assert localized.instructions_zh_cn == (
        "将杠铃置于上背部。",
        "屈髋屈膝下蹲。",
    )
    assert bundle.taxonomy is not None
    assert bundle.taxonomy.equipment["e-z curl bar"] == "EZ 杠"


def test_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text(
        """{
          "schema_version": 1,
          "source_name": "Taiwan FDA Food Nutrient Database",
          "locale": "zh-CN",
          "entries": {
            "A001": {"name_zh_cn": "米饭", "aliases": []},
            "A001": {"name_zh_cn": "米粥", "aliases": []}
          }
        }""",
        encoding="utf-8",
    )

    with pytest.raises(ReceiverError) as raised:
        load_localization_bundle(catalog_kind="food", localization_path=path)

    assert raised.value.code == "LOCALIZATION_INVALID"


def test_rejects_wrong_source_name(tmp_path: Path) -> None:
    path = _localized_copy(
        tmp_path,
        FOOD_LOCALIZATION,
        {"source_name": "free-exercise-db"},
    )

    with pytest.raises(ReceiverError) as raised:
        load_localization_bundle(catalog_kind="food", localization_path=path)

    assert raised.value.code == "LOCALIZATION_INVALID"


def test_reports_missing_and_orphan_source_ids() -> None:
    bundle = load_localization_bundle(
        catalog_kind="food",
        localization_path=FOOD_LOCALIZATION,
    )

    issues = validate_localization_coverage(bundle, {"A001", "A003"})

    assert [(issue.code, issue.record) for issue in issues] == [
        ("LOCALIZATION_MISSING", "A003"),
        ("LOCALIZATION_ORPHAN", "A002"),
    ]


def test_rejects_instruction_count_mismatch() -> None:
    bundle = load_localization_bundle(
        catalog_kind="exercise",
        localization_path=EXERCISE_LOCALIZATION,
        taxonomy_path=EXERCISE_TAXONOMY,
    )

    with pytest.raises(ReceiverError) as raised:
        bundle.exercise("Barbell_Full_Squat", instruction_count=1)

    assert raised.value.code == "LOCALIZATION_INSTRUCTION_COUNT_MISMATCH"
    assert raised.value.issue is not None
    assert raised.value.issue.record == "Barbell_Full_Squat"


def test_rejects_duplicate_canonical_names(tmp_path: Path) -> None:
    payload = json.loads(EXERCISE_LOCALIZATION.read_text(encoding="utf-8"))
    payload["entries"]["Pushups"]["name_zh_cn"] = "杠铃深蹲"
    path = _localized_copy(tmp_path, EXERCISE_LOCALIZATION, payload)

    with pytest.raises(ReceiverError) as raised:
        load_localization_bundle(
            catalog_kind="exercise",
            localization_path=path,
            taxonomy_path=EXERCISE_TAXONOMY,
        )

    assert raised.value.code == "LOCALIZATION_NAME_COLLISION"


def test_rejects_alias_equal_to_canonical_name_after_normalization(tmp_path: Path) -> None:
    payload = json.loads(EXERCISE_LOCALIZATION.read_text(encoding="utf-8"))
    payload["entries"]["Barbell_Full_Squat"].update(
        {
            "name_zh_cn": "TRX 深蹲",
            "aliases": ["ｔｒｘ 深蹲"],
        }
    )
    path = _localized_copy(tmp_path, EXERCISE_LOCALIZATION, payload)

    with pytest.raises(ReceiverError) as raised:
        load_localization_bundle(
            catalog_kind="exercise",
            localization_path=path,
            taxonomy_path=EXERCISE_TAXONOMY,
        )

    assert raised.value.code == "LOCALIZATION_ALIAS_REDUNDANT"


def test_rejects_unapproved_latin_text(tmp_path: Path) -> None:
    payload = json.loads(EXERCISE_LOCALIZATION.read_text(encoding="utf-8"))
    payload["entries"]["Barbell_Full_Squat"]["name_zh_cn"] = "Barbell 深蹲"
    path = _localized_copy(tmp_path, EXERCISE_LOCALIZATION, payload)

    with pytest.raises(ReceiverError) as raised:
        load_localization_bundle(
            catalog_kind="exercise",
            localization_path=path,
            taxonomy_path=EXERCISE_TAXONOMY,
        )

    assert raised.value.code == "LOCALIZATION_LATIN_UNAPPROVED"
