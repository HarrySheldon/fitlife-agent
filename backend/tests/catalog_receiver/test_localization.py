from __future__ import annotations

import json
import stat
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.catalog_receiver import localization as localization_module
from backend.catalog_receiver.localization import (
    ExerciseLocalizationAsset,
    FoodLocalizationAsset,
    load_localization_bundle,
    validate_localization_coverage,
)
from backend.catalog_receiver.models import ReceiverError


FIXTURES = Path(__file__).parent / "fixtures"
FOOD_LOCALIZATION = FIXTURES / "food-localization.zh-CN.json"
EXERCISE_LOCALIZATION = FIXTURES / "exercise-localization.zh-CN.json"
EXERCISE_TAXONOMY = FIXTURES / "exercise-taxonomy.zh-CN.json"
CATALOG_EXERCISE_TAXONOMY = (
    Path(__file__).parents[2]
    / "data"
    / "catalog"
    / "localizations"
    / "exercise-taxonomy.zh-CN.v1.json"
)
EXERCISE_SNAPSHOT = Path(__file__).parents[2] / "data" / "catalog" / "exercises.zh-CN.v1.json"


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

    assert bundle.schema_version == 1
    assert bundle.version == "1.0.0"
    assert bundle.locale == "zh-CN"
    assert bundle.source_name == "Taiwan FDA Food Nutrient Database"
    assert bundle.localization_path == FOOD_LOCALIZATION.resolve()
    assert bundle.taxonomy_path is None
    assert [rule.model_dump() for rule in bundle.food_glossary] == [
        {"source": "白饭", "target": "米饭", "match_mode": "exact", "priority": 10},
        {"source": "马铃薯", "target": "土豆", "match_mode": "exact", "priority": 20},
    ]
    assert localized.name_zh_cn == "米饭"
    assert localized.aliases == ("白飯", "Cooked rice")
    with pytest.raises(TypeError):
        bundle.food_entries["A003"] = localized  # type: ignore[index]
    with pytest.raises(TypeError):
        dict.__setitem__(bundle.food_entries, "A003", localized)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        bundle.food_glossary[0].target = "粥"
    with pytest.raises(AttributeError):
        bundle.food_glossary.append(bundle.food_glossary[0])  # type: ignore[attr-defined]


def test_rejects_food_glossary_without_explicit_priority(tmp_path: Path) -> None:
    payload = json.loads(FOOD_LOCALIZATION.read_text(encoding="utf-8"))
    del payload["glossary"][0]["priority"]
    path = _localized_copy(tmp_path, FOOD_LOCALIZATION, payload)

    with pytest.raises(ReceiverError) as raised:
        load_localization_bundle(catalog_kind="food", localization_path=path)

    assert raised.value.code == "LOCALIZATION_INVALID"


def test_rejects_duplicate_food_glossary_priorities(tmp_path: Path) -> None:
    payload = json.loads(FOOD_LOCALIZATION.read_text(encoding="utf-8"))
    payload["glossary"][1]["priority"] = payload["glossary"][0]["priority"]
    path = _localized_copy(tmp_path, FOOD_LOCALIZATION, payload)

    with pytest.raises(ReceiverError) as raised:
        load_localization_bundle(catalog_kind="food", localization_path=path)

    assert raised.value.code == "LOCALIZATION_INVALID"


def test_loads_valid_exercise_and_taxonomy_assets() -> None:
    bundle = load_localization_bundle(
        catalog_kind="exercise",
        localization_path=EXERCISE_LOCALIZATION,
        taxonomy_path=EXERCISE_TAXONOMY,
    )

    localized = bundle.exercise("Barbell_Full_Squat", instruction_count=2)

    assert bundle.schema_version == 1
    assert bundle.version == "2.0.0"
    assert bundle.locale == "zh-CN"
    assert bundle.source_name == "free-exercise-db"
    assert bundle.localization_path == EXERCISE_LOCALIZATION.resolve()
    assert bundle.taxonomy_path == EXERCISE_TAXONOMY.resolve()
    assert localized.name_zh_cn == "杠铃深蹲"
    assert localized.instructions_zh_cn == (
        "将杠铃置于上背部。",
        "屈髋屈膝下蹲。",
    )
    assert bundle.taxonomy is not None
    assert bundle.taxonomy.schema_version == 1
    assert bundle.taxonomy.version == "1.0.0"
    assert bundle.taxonomy.locale == "zh-CN"
    assert bundle.taxonomy.source_name == "free-exercise-db"
    assert bundle.taxonomy.equipment["e-z curl bar"] == "EZ 杠"


def test_catalog_exercise_taxonomy_covers_all_snapshot_upstream_values() -> None:
    bundle = load_localization_bundle(
        catalog_kind="exercise",
        localization_path=EXERCISE_LOCALIZATION,
        taxonomy_path=CATALOG_EXERCISE_TAXONOMY,
    )

    taxonomy = bundle.taxonomy
    assert taxonomy is not None
    snapshot = json.loads(EXERCISE_SNAPSHOT.read_text(encoding="utf-8"))
    exercises = snapshot["exercises"]
    assert len(exercises) == 750
    muscles = {
        muscle
        for exercise in exercises
        for muscle in (
            exercise["primary_muscle"],
            *exercise["secondary_muscles"],
        )
    }
    provenance_taxonomy = {
        field: {
            exercise["provenance"][source_field]
            for exercise in exercises
            if exercise["provenance"].get(source_field) is not None
        }
        for field, source_field in (
            ("equipment", "equipment"),
            ("levels", "level"),
            ("mechanics", "mechanic"),
            ("forces", "force"),
            ("categories", "original_category"),
        )
    }

    assert taxonomy.approved_latin == ("EZ", "T", "TRX")
    assert muscles == set(taxonomy.muscles)
    for field, upstream_values in provenance_taxonomy.items():
        assert upstream_values == set(getattr(taxonomy, field))


def test_immutable_models_serialize_to_json_without_warnings() -> None:
    food_bundle = load_localization_bundle(
        catalog_kind="food",
        localization_path=FOOD_LOCALIZATION,
    )
    exercise_bundle = load_localization_bundle(
        catalog_kind="exercise",
        localization_path=EXERCISE_LOCALIZATION,
        taxonomy_path=EXERCISE_TAXONOMY,
    )
    assert exercise_bundle.taxonomy is not None
    models = (
        FoodLocalizationAsset(
            schema_version=1,
            version="1.0.0",
            source_name="Taiwan FDA Food Nutrient Database",
            locale="zh-CN",
            glossary=food_bundle.food_glossary,
            entries=food_bundle.food_entries,
        ),
        ExerciseLocalizationAsset(
            schema_version=1,
            version="2.0.0",
            source_name="free-exercise-db",
            locale="zh-CN",
            entries=exercise_bundle.exercise_entries,
        ),
        exercise_bundle.taxonomy,
        food_bundle,
        exercise_bundle,
    )
    assert models[0].model_dump(mode="json")["glossary"] == [
        {"source": "白饭", "target": "米饭", "match_mode": "exact", "priority": 10},
        {"source": "马铃薯", "target": "土豆", "match_mode": "exact", "priority": 20},
    ]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for model in models:
            dumped = model.model_dump(mode="json")
            assert json.loads(model.model_dump_json()) == dumped

    assert caught == []


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


def test_missing_taxonomy_identifies_taxonomy_path(tmp_path: Path) -> None:
    taxonomy_path = tmp_path / "missing-taxonomy.json"

    with pytest.raises(ReceiverError) as raised:
        load_localization_bundle(
            catalog_kind="exercise",
            localization_path=EXERCISE_LOCALIZATION,
            taxonomy_path=taxonomy_path,
        )

    assert raised.value.code == "LOCALIZATION_INVALID"
    assert taxonomy_path.name in raised.value.message
    assert "not found" in raised.value.message.casefold()
    assert raised.value.issue is not None
    assert raised.value.issue.source_path == str(taxonomy_path.resolve())


def test_malformed_taxonomy_identifies_taxonomy_path(tmp_path: Path) -> None:
    taxonomy_path = tmp_path / "malformed-taxonomy.json"
    taxonomy_path.write_text('{"schema_version":', encoding="utf-8")

    with pytest.raises(ReceiverError) as raised:
        load_localization_bundle(
            catalog_kind="exercise",
            localization_path=EXERCISE_LOCALIZATION,
            taxonomy_path=taxonomy_path,
        )

    assert raised.value.code == "LOCALIZATION_INVALID"
    assert taxonomy_path.name in raised.value.message
    assert "malformed JSON" in raised.value.message
    assert raised.value.issue is not None
    assert raised.value.issue.source_path == str(taxonomy_path.resolve())


def test_rejects_url_without_exposing_credentials() -> None:
    source = "https://reader:secret@example.com/localization.json?token=hidden"

    with pytest.raises(ReceiverError) as raised:
        load_localization_bundle(catalog_kind="food", localization_path=source)

    assert raised.value.code == "LOCALIZATION_INVALID"
    assert "local files" in raised.value.message
    assert "secret" not in raised.value.message
    assert "hidden" not in raised.value.message
    assert raised.value.issue is not None
    assert raised.value.issue.source_path == "https://example.com/localization.json"


def test_rejects_malformed_url_with_sanitized_error() -> None:
    with pytest.raises(ReceiverError) as raised:
        load_localization_bundle(catalog_kind="food", localization_path="https://[")

    assert raised.value.code == "LOCALIZATION_INVALID"
    assert raised.value.issue is not None
    assert raised.value.issue.source_path == "https://<invalid>"


def test_rejects_unc_path_before_filesystem_access() -> None:
    source = r"\\server\share\localization.json"

    with pytest.raises(ReceiverError) as raised:
        load_localization_bundle(catalog_kind="food", localization_path=source)

    assert raised.value.code == "LOCALIZATION_INVALID"
    assert "UNC paths are not supported" in raised.value.message
    assert raised.value.issue is not None
    assert raised.value.issue.source_path == source


def test_rejects_oversized_asset_from_bounded_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "oversized-localization.json"
    path.write_bytes(b" " * (localization_module.LOCALIZATION_JSON_SIZE_LIMIT + 1))
    real_stat = path.stat()
    original_stat = Path.stat

    def underreported_stat(candidate: Path, *args: object, **kwargs: object) -> object:
        if candidate == path:
            return SimpleNamespace(st_mode=real_stat.st_mode, st_size=0)
        return original_stat(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", underreported_stat)

    with pytest.raises(ReceiverError) as raised:
        load_localization_bundle(catalog_kind="food", localization_path=path)

    assert raised.value.code == "LOCALIZATION_INVALID"
    assert "size limit" in raised.value.message
    assert raised.value.issue is not None
    assert raised.value.issue.source_path == str(path.resolve())


def test_rejects_non_regular_open_handle_before_read(monkeypatch: pytest.MonkeyPatch) -> None:
    class NonRegularStream:
        def __enter__(self) -> "NonRegularStream":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def fileno(self) -> int:
            return 123

        def read(self, _size: int) -> bytes:
            raise AssertionError("non-regular input must be rejected before read")

    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: NonRegularStream())
    monkeypatch.setattr(
        localization_module,
        "os",
        SimpleNamespace(fstat=lambda _fd: SimpleNamespace(st_mode=stat.S_IFIFO)),
        raising=False,
    )

    with pytest.raises(ReceiverError) as raised:
        load_localization_bundle(catalog_kind="food", localization_path=FOOD_LOCALIZATION)

    assert raised.value.code == "LOCALIZATION_INVALID"
    assert "regular file" in raised.value.message


@pytest.mark.parametrize("device_name", ["NUL", "CON"])
def test_rejects_windows_reserved_device_without_opening(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    device_name: str,
) -> None:
    source = tmp_path / device_name

    def unexpected_open(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("reserved device path must be rejected before open")

    monkeypatch.setattr(Path, "open", unexpected_open)

    with pytest.raises(ReceiverError) as raised:
        load_localization_bundle(catalog_kind="food", localization_path=source)

    assert raised.value.code == "LOCALIZATION_INVALID"
    assert "reserved device" in raised.value.message
    assert raised.value.issue is not None
    assert raised.value.issue.source_path == str(source.absolute())


def test_sparse_food_coverage_reports_only_orphan_source_ids() -> None:
    bundle = load_localization_bundle(
        catalog_kind="food",
        localization_path=FOOD_LOCALIZATION,
    )

    issues = validate_localization_coverage(bundle, {"A001", "A003"})

    assert [(issue.code, issue.record) for issue in issues] == [
        ("LOCALIZATION_ORPHAN", "A002"),
    ]
    assert {issue.source_path for issue in issues} == {str(FOOD_LOCALIZATION.resolve())}


def test_exercise_coverage_remains_exact_by_source_id() -> None:
    bundle = load_localization_bundle(
        catalog_kind="exercise",
        localization_path=EXERCISE_LOCALIZATION,
        taxonomy_path=EXERCISE_TAXONOMY,
    )

    issues = validate_localization_coverage(
        bundle,
        {"Barbell_Full_Squat", "Missing_Exercise"},
    )

    assert [(issue.code, issue.record) for issue in issues] == [
        ("LOCALIZATION_MISSING", "Missing_Exercise"),
        ("LOCALIZATION_ORPHAN", "Pushups"),
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
    assert raised.value.issue.source_path == str(EXERCISE_LOCALIZATION.resolve())


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


@pytest.mark.parametrize(
    "pinyin",
    [
        "深蹲",
        "gangling_shendun",
        "gānglíng shēndūn",
        "ſhen dun",
        "Kang ling",
        "-",
        "123",
        "1shen",
        "shen0",
        "shen6",
        "shen12",
        "shen2dun",
        " shen",
        "shen ",
        "-shen",
        "shen-",
        "shen  dun",
        "shen--dun",
        "shen -dun",
    ],
)
def test_rejects_malformed_exercise_pinyin(tmp_path: Path, pinyin: str) -> None:
    payload = json.loads(EXERCISE_LOCALIZATION.read_text(encoding="utf-8"))
    payload["entries"]["Barbell_Full_Squat"]["pinyin"] = [pinyin]
    path = _localized_copy(tmp_path, EXERCISE_LOCALIZATION, payload)

    with pytest.raises(ReceiverError) as raised:
        load_localization_bundle(
            catalog_kind="exercise",
            localization_path=path,
            taxonomy_path=EXERCISE_TAXONOMY,
        )

    assert raised.value.code == "LOCALIZATION_INVALID"


@pytest.mark.parametrize(
    "pinyin",
    ["gangling shendun", "Gang2-Ling2 Shen1-Dun1", "TRX shendun"],
)
def test_preserves_valid_authored_exercise_pinyin(
    tmp_path: Path,
    pinyin: str,
) -> None:
    payload = json.loads(EXERCISE_LOCALIZATION.read_text(encoding="utf-8"))
    payload["entries"]["Barbell_Full_Squat"]["pinyin"] = [pinyin]
    path = _localized_copy(tmp_path, EXERCISE_LOCALIZATION, payload)

    bundle = load_localization_bundle(
        catalog_kind="exercise",
        localization_path=path,
        taxonomy_path=EXERCISE_TAXONOMY,
    )

    assert bundle.exercise_entries["Barbell_Full_Squat"].pinyin == (pinyin,)


@pytest.mark.parametrize(
    ("field", "duplicate"),
    [
        ("aliases", "杠铃深蹲"),
        ("pinyin", "barbell full squat"),
    ],
)
def test_rejects_exercise_alias_and_pinyin_cross_field_duplicates(
    tmp_path: Path,
    field: str,
    duplicate: str,
) -> None:
    payload = json.loads(EXERCISE_LOCALIZATION.read_text(encoding="utf-8"))
    entry = payload["entries"]["Barbell_Full_Squat"]
    if field == "pinyin":
        entry["aliases"] = ["Ｂａｒｂｅｌｌ Ｆｕｌｌ Ｓｑｕａｔ"]
    entry[field] = [duplicate]
    path = _localized_copy(tmp_path, EXERCISE_LOCALIZATION, payload)

    with pytest.raises(ReceiverError) as raised:
        load_localization_bundle(
            catalog_kind="exercise",
            localization_path=path,
            taxonomy_path=EXERCISE_TAXONOMY,
        )

    assert raised.value.code == "LOCALIZATION_ALIAS_REDUNDANT"
    assert raised.value.issue is not None
    assert raised.value.issue.field == field


def test_rejects_exercise_canonical_name_and_pinyin_duplicate(tmp_path: Path) -> None:
    payload = json.loads(EXERCISE_LOCALIZATION.read_text(encoding="utf-8"))
    entry = payload["entries"]["Barbell_Full_Squat"]
    entry["name_zh_cn"] = "TRX"
    entry["aliases"] = []
    entry["pinyin"] = ["trx"]
    path = _localized_copy(tmp_path, EXERCISE_LOCALIZATION, payload)

    with pytest.raises(ReceiverError) as raised:
        load_localization_bundle(
            catalog_kind="exercise",
            localization_path=path,
            taxonomy_path=EXERCISE_TAXONOMY,
        )

    assert raised.value.code == "LOCALIZATION_ALIAS_REDUNDANT"
    assert raised.value.issue is not None
    assert raised.value.issue.field == "pinyin"


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


@pytest.mark.parametrize("name_zh_cn", ["é 深蹲", "TRX\u0338 深蹲", "TRX2 深蹲"])
def test_rejects_unicode_latin_tokens_not_exactly_approved(
    tmp_path: Path,
    name_zh_cn: str,
) -> None:
    payload = json.loads(EXERCISE_LOCALIZATION.read_text(encoding="utf-8"))
    payload["entries"]["Barbell_Full_Squat"]["name_zh_cn"] = name_zh_cn
    path = _localized_copy(tmp_path, EXERCISE_LOCALIZATION, payload)

    with pytest.raises(ReceiverError) as raised:
        load_localization_bundle(
            catalog_kind="exercise",
            localization_path=path,
            taxonomy_path=EXERCISE_TAXONOMY,
        )

    assert raised.value.code == "LOCALIZATION_LATIN_UNAPPROVED"


def test_allows_nfkc_equivalent_unicode_latin_token(tmp_path: Path) -> None:
    localization = json.loads(EXERCISE_LOCALIZATION.read_text(encoding="utf-8"))
    localization["entries"]["Barbell_Full_Squat"]["name_zh_cn"] = "Cafe\u0301 深蹲"
    localization_path = _localized_copy(tmp_path, EXERCISE_LOCALIZATION, localization)
    taxonomy = json.loads(EXERCISE_TAXONOMY.read_text(encoding="utf-8"))
    taxonomy["approved_latin"].append("CAFÉ")
    taxonomy_path = _localized_copy(tmp_path, EXERCISE_TAXONOMY, taxonomy)

    bundle = load_localization_bundle(
        catalog_kind="exercise",
        localization_path=localization_path,
        taxonomy_path=taxonomy_path,
    )

    assert bundle.exercise("Barbell_Full_Squat", instruction_count=2).name_zh_cn == "Cafe\u0301 深蹲"


@pytest.mark.parametrize("name_zh_cn", ["⒜ 深蹲", "𝐀 深蹲"])
def test_rejects_nfkc_compatibility_latin_forms(
    tmp_path: Path,
    name_zh_cn: str,
) -> None:
    payload = json.loads(EXERCISE_LOCALIZATION.read_text(encoding="utf-8"))
    payload["entries"]["Barbell_Full_Squat"]["name_zh_cn"] = name_zh_cn
    path = _localized_copy(tmp_path, EXERCISE_LOCALIZATION, payload)

    with pytest.raises(ReceiverError) as raised:
        load_localization_bundle(
            catalog_kind="exercise",
            localization_path=path,
            taxonomy_path=EXERCISE_TAXONOMY,
        )

    assert raised.value.code == "LOCALIZATION_LATIN_UNAPPROVED"
