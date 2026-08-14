import json
import os
from pathlib import Path

from scripts import build_localized_catalogs as build_module
from scripts.build_localized_catalogs import main


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def _food_record(source_id: str, name: str, upstream_name: str) -> dict:
    return {
        "source_name": "Taiwan FDA Food Nutrient Database",
        "source_record_id": source_id,
        "dataset_version": "2025-12-22",
        "license": "Taiwan Government Open Data License 1.0",
        "attribution": "Taiwan Food and Drug Administration",
        "name": name,
        "basis_type": "per_100g",
        "basis_amount": 100,
        "unit": "g",
        "calories": 100,
        "carbs": 20,
        "protein": 3,
        "fat": 1,
        "aliases": [upstream_name, f"{source_id} food"],
        "provenance": {
            "profile": "tfda-foods@1.0.0",
            "food_category": "穀物類",
            "description": f"{upstream_name} description",
            "nutrient_basis": "每100克含量",
            "name_conversion": "opencc_t2s",
        },
    }


def _exercise_record() -> dict:
    return {
        "source_name": "free-exercise-db",
        "source_record_id": "Barbell_Full_Squat",
        "dataset_version": "2026-08-09",
        "license": "Unlicense",
        "attribution": "free-exercise-db contributors",
        "name": "Barbell Full Squat",
        "exercise_type": "strength",
        "primary_muscle": "quadriceps",
        "secondary_muscles": ["calves", "glutes"],
        "met": None,
        "aliases": [],
        "provenance": {
            "profile": "free-exercise-db@1.0.0",
            "upstream_name": "Barbell Full Squat",
            "original_category": "strength",
            "equipment": "barbell",
            "level": "intermediate",
            "mechanic": "compound",
            "force": "push",
            "instructions": ["Stand with the bar.", "Squat."],
            "image_count": 1,
        },
    }


def _build_args(tmp_path: Path) -> tuple[list[str], Path, Path]:
    food_catalog = _write_json(
        tmp_path / "foods.json",
        {
            "schema_version": 1,
            "source_name": "Taiwan FDA Food Nutrient Database",
            "dataset_version": "2025-12-22",
            "license": "Taiwan Government Open Data License 1.0",
            "attribution": "Taiwan Food and Drug Administration",
            "foods": [
                _food_record("B002", "馬鈴薯", "馬鈴薯"),
                _food_record("A001", "白飯", "白飯"),
            ],
        },
    )
    exercise_catalog = _write_json(
        tmp_path / "exercises.json",
        {
            "schema_version": 1,
            "dataset_version": "2026-08-09",
            "managed_sources": ["free-exercise-db"],
            "exercises": [_exercise_record()],
        },
    )
    food_localization = _write_json(
        tmp_path / "food-localization.json",
        {
            "schema_version": 1,
            "version": "1.0.0",
            "source_name": "Taiwan FDA Food Nutrient Database",
            "locale": "zh-CN",
            "glossary": [],
            "entries": {
                "A001": {
                    "name_zh_cn": "米饭",
                    "review_note": "Approved fixture override.",
                },
                "B002": {
                    "name_zh_cn": "土豆",
                    "review_note": "Approved fixture override.",
                },
            },
        },
    )
    exercise_localization = _write_json(
        tmp_path / "exercise-localization.json",
        {
            "schema_version": 1,
            "version": "2.0.0",
            "source_name": "free-exercise-db",
            "locale": "zh-CN",
            "entries": {
                "Barbell_Full_Squat": {
                    "name_zh_cn": "杠铃深蹲",
                    "aliases": ["深蹲"],
                    "instructions_zh_cn": ["将杠铃置于上背部。", "屈髋屈膝下蹲。"],
                }
            },
        },
    )
    taxonomy = _write_json(
        tmp_path / "exercise-taxonomy.json",
        {
            "schema_version": 1,
            "version": "1.0.0",
            "source_name": "free-exercise-db",
            "locale": "zh-CN",
            "approved_latin": [],
            "muscles": {
                "quadriceps": "股四头肌",
                "calves": "小腿肌",
                "glutes": "臀肌",
            },
            "equipment": {"barbell": "杠铃"},
            "levels": {"intermediate": "中级"},
            "mechanics": {"compound": "复合动作"},
            "forces": {"push": "推"},
            "categories": {"strength": "力量训练"},
        },
    )
    args = [
        "--foods", str(food_catalog),
        "--food-localization", str(food_localization),
        "--exercises", str(exercise_catalog),
        "--exercise-localization", str(exercise_localization),
        "--exercise-taxonomy", str(taxonomy),
        "--food-output", str(food_catalog),
        "--exercise-output", str(exercise_catalog),
    ]
    return args, food_catalog, exercise_catalog


def test_build_is_sorted_and_byte_idempotent(tmp_path: Path) -> None:
    args, food_catalog, exercise_catalog = _build_args(tmp_path)

    assert main(args) == 0
    first_food = food_catalog.read_bytes()
    first_exercise = exercise_catalog.read_bytes()
    foods = json.loads(first_food.decode("utf-8"))["foods"]
    exercises = json.loads(first_exercise.decode("utf-8"))["exercises"]

    assert [record["source_record_id"] for record in foods] == ["A001", "B002"]
    assert [record["name"] for record in foods] == ["米饭", "土豆"]
    assert exercises[0]["name"] == "杠铃深蹲"
    assert exercises[0]["provenance"]["upstream_name"] == "Barbell Full Squat"
    assert exercises[0]["provenance"]["upstream"]["instructions"] == [
        "Stand with the bar.",
        "Squat.",
    ]

    assert main(args) == 0
    assert food_catalog.read_bytes() == first_food
    assert exercise_catalog.read_bytes() == first_exercise


def test_missing_upstream_text_preserves_both_outputs(
    tmp_path: Path,
    capsys,
) -> None:
    args, food_catalog, exercise_catalog = _build_args(tmp_path)
    food_payload = json.loads(food_catalog.read_text(encoding="utf-8"))
    food_payload["foods"][0]["aliases"] = []
    _write_json(food_catalog, food_payload)
    original_food = food_catalog.read_bytes()
    original_exercise = exercise_catalog.read_bytes()

    assert main(args) == 4

    assert "UPSTREAM_SOURCE_TEXT_MISSING" in capsys.readouterr().err
    assert food_catalog.read_bytes() == original_food
    assert exercise_catalog.read_bytes() == original_exercise
    assert list(tmp_path.glob(".*.tmp")) == []
    assert list(tmp_path.glob(".*.bak")) == []


def test_second_replace_failure_rolls_back_both_outputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    args, food_catalog, exercise_catalog = _build_args(tmp_path)
    original_food = food_catalog.read_bytes()
    original_exercise = exercise_catalog.read_bytes()
    real_replace = Path.replace
    failed = False

    def fail_second_replace(path: Path, target: Path) -> Path:
        nonlocal failed
        if (
            not failed
            and path.name.startswith(f".{exercise_catalog.name}.")
            and path.suffix == ".tmp"
        ):
            failed = True
            raise OSError("forced second replacement failure")
        return real_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_second_replace)

    assert main(args) == 5
    assert failed is True
    assert food_catalog.read_bytes() == original_food
    assert exercise_catalog.read_bytes() == original_exercise
    assert list(tmp_path.glob(".*.tmp")) == []
    assert list(tmp_path.glob(".*.bak")) == []


def test_restore_failure_retains_unrecovered_backup_with_diagnostic(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    args, food_catalog, exercise_catalog = _build_args(tmp_path)
    original_food = food_catalog.read_bytes()
    original_exercise = exercise_catalog.read_bytes()
    real_replace = Path.replace
    failed_second_replace = False
    failed_restore = False
    retained_backup: Path | None = None

    def fail_replace_and_restore(path: Path, target: Path) -> Path:
        nonlocal failed_second_replace, failed_restore, retained_backup
        if (
            not failed_second_replace
            and path.name.startswith(f".{exercise_catalog.name}.")
            and path.suffix == ".tmp"
        ):
            failed_second_replace = True
            raise OSError("forced second replacement failure")
        if (
            failed_second_replace
            and not failed_restore
            and path.name.startswith(f".{food_catalog.name}.")
            and path.suffix == ".bak"
        ):
            failed_restore = True
            retained_backup = path
            raise OSError("forced backup restoration failure")
        return real_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_replace_and_restore)

    assert main(args) == 5

    error = json.loads(capsys.readouterr().err)["error"]
    assert error["code"] == "CATALOG_ROLLBACK_INCOMPLETE"
    assert failed_second_replace is True
    assert failed_restore is True
    assert retained_backup is not None
    assert str(retained_backup) in error["message"]
    assert retained_backup.read_bytes() == original_food
    assert exercise_catalog.read_bytes() == original_exercise
    assert list(tmp_path.glob(".*.tmp")) == []
    assert list(tmp_path.glob(".*.bak")) == [retained_backup]


def test_atomic_outputs_use_sibling_temps_fsynced_before_replacement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    args, _food_catalog, _exercise_catalog = _build_args(tmp_path)
    real_fsync = os.fsync
    real_replace = Path.replace
    events: list[tuple[str, object]] = []

    def record_fsync(file_descriptor: int) -> None:
        events.append(("fsync", os.fstat(file_descriptor).st_size))
        real_fsync(file_descriptor)

    def record_replace(path: Path, target: Path) -> Path:
        if path.suffix == ".tmp":
            events.append(("replace", (path, target)))
        return real_replace(path, target)

    monkeypatch.setattr(build_module.os, "fsync", record_fsync)
    monkeypatch.setattr(Path, "replace", record_replace)

    assert main(args) == 0

    replace_indexes = [
        index for index, (event, _detail) in enumerate(events) if event == "replace"
    ]
    assert len(replace_indexes) == 2
    assert all(
        detail > 0
        for event, detail in events[: replace_indexes[0]]
        if event == "fsync"
    )
    assert sum(
        event == "fsync" for event, _detail in events[: replace_indexes[0]]
    ) == 4
    for index in replace_indexes:
        temporary, output = events[index][1]
        assert temporary.parent == output.parent
        assert temporary.name.startswith(f".{output.name}.")
