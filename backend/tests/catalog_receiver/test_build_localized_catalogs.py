import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import build_localized_catalogs as build_module
from scripts.build_localized_catalogs import main


MAPPING_ROOT = Path(build_module.__file__).parents[1] / "backend/data/catalog/mappings"


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
    legacy_search_terms = _write_json(
        tmp_path / "legacy-search-terms.json",
        {
            "schema_version": 1,
            "foods": {
                "A001": ["Legacy rice", "ＭＩＦＡＮ", "mifan"],
            },
            "exercises": {
                "Barbell_Full_Squat": [
                    "Legacy full squat",
                    "ＢＡＲＢＥＬＬ ＦＵＬＬ ＳＱＵＡＴ",
                    "Barbell Full Squat",
                ],
            },
        },
    )
    args = [
        "--foods", str(food_catalog),
        "--food-localization", str(food_localization),
        "--exercises", str(exercise_catalog),
        "--exercise-localization", str(exercise_localization),
        "--exercise-taxonomy", str(taxonomy),
        "--legacy-search-terms", str(legacy_search_terms),
        "--food-output", str(food_catalog),
        "--exercise-output", str(exercise_catalog),
    ]
    return args, food_catalog, exercise_catalog


def _argument_path(args: list[str], option: str) -> Path:
    return Path(args[args.index(option) + 1])


def _with_argument(args: list[str], option: str, value: Path) -> list[str]:
    updated = list(args)
    updated[updated.index(option) + 1] = str(value)
    return updated


def test_build_is_sorted_and_byte_idempotent(tmp_path: Path) -> None:
    args, food_catalog, exercise_catalog = _build_args(tmp_path)

    assert main(args) == 0
    first_food = food_catalog.read_bytes()
    first_exercise = exercise_catalog.read_bytes()
    foods = json.loads(first_food.decode("utf-8"))["foods"]
    exercises = json.loads(first_exercise.decode("utf-8"))["exercises"]

    assert [record["source_record_id"] for record in foods] == ["A001", "B002"]
    assert [record["name"] for record in foods] == ["米饭", "土豆"]
    assert foods[0]["aliases"] == [
        "白飯",
        "白饭",
        "A001 food",
        "Legacy rice",
        "ＭＩＦＡＮ",
    ]
    assert exercises[0]["name"] == "杠铃深蹲"
    assert exercises[0]["aliases"] == [
        "Barbell Full Squat",
        "深蹲",
        "Legacy full squat",
    ]
    assert exercises[0]["provenance"]["upstream_name"] == "Barbell Full Squat"
    assert exercises[0]["provenance"]["upstream"]["instructions"] == [
        "Stand with the bar.",
        "Squat.",
    ]

    assert main(args) == 0
    assert food_catalog.read_bytes() == first_food
    assert exercise_catalog.read_bytes() == first_exercise


@pytest.mark.parametrize(
    ("output_option", "conflicting_role"),
    [
        ("--food-output", "--exercises"),
        ("--exercise-output", "--foods"),
        ("--exercise-output", "--food-output"),
        ("--food-output", "--food-localization"),
        ("--exercise-output", "--exercise-localization"),
        ("--exercise-output", "--exercise-taxonomy"),
        ("--exercise-output", "lock"),
        ("--exercise-output", "manifest"),
        ("--exercise-output", "food-next"),
        ("--exercise-output", "food-backup"),
    ],
)
def test_build_rejects_conflicting_resolved_role_paths(
    tmp_path: Path,
    capsys,
    output_option: str,
    conflicting_role: str,
) -> None:
    args, food_catalog, _exercise_catalog = _build_args(tmp_path)
    controls = {
        "lock": tmp_path / ".catalog-localization.publish.lock",
        "manifest": tmp_path / ".catalog-localization.publish.json",
        "food-next": food_catalog.with_name(f".{food_catalog.name}.catalog.next"),
        "food-backup": food_catalog.with_name(
            f".{food_catalog.name}.catalog.backup"
        ),
    }
    conflict = (
        _argument_path(args, conflicting_role)
        if conflicting_role.startswith("--")
        else controls[conflicting_role]
    )

    assert main(_with_argument(args, output_option, conflict)) == 4
    assert "CATALOG_PATH_CONFLICT" in capsys.readouterr().err


def test_build_rejects_existing_hardlink_role_alias(
    tmp_path: Path,
    capsys,
) -> None:
    args, food_catalog, _exercise_catalog = _build_args(tmp_path)
    aliased_output = tmp_path / "food-input-hardlink.json"
    os.link(food_catalog, aliased_output)

    assert main(_with_argument(args, "--exercise-output", aliased_output)) == 4
    assert "CATALOG_PATH_CONFLICT" in capsys.readouterr().err


@pytest.mark.parametrize(
    "mapping_name",
    ["tfda-foods.v1.json", "free-exercise-db.v1.json"],
)
def test_build_protects_fixed_mapping_profile_paths(
    tmp_path: Path,
    capsys,
    mapping_name: str,
) -> None:
    args, _food_catalog, _exercise_catalog = _build_args(tmp_path)
    mapping_path = MAPPING_ROOT / mapping_name
    original_mapping = mapping_path.read_bytes()

    assert main(_with_argument(args, "--exercise-output", mapping_path)) == 4
    assert "CATALOG_PATH_CONFLICT" in capsys.readouterr().err
    assert mapping_path.read_bytes() == original_mapping


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
            and path.name == f".{exercise_catalog.name}.catalog.next"
        ):
            failed = True
            raise OSError("forced second replacement failure")
        return real_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_second_replace)

    assert main(args) == 5
    assert failed is True
    assert food_catalog.read_bytes() == original_food
    assert exercise_catalog.read_bytes() == original_exercise
    assert list(tmp_path.glob("*.catalog.next")) == []
    assert list(tmp_path.glob("*.catalog.backup")) == []
    assert not (tmp_path / ".catalog-localization.publish.json").exists()


@pytest.mark.parametrize(
    ("checkpoint", "committed"),
    [
        ("prepared", False),
        ("food_output_replaced", False),
        ("food_replaced", False),
        ("exercise_output_replaced", False),
        ("both_replaced", False),
        ("committed", True),
    ],
)
def test_next_build_recovers_each_interrupted_publication_phase(
    tmp_path: Path,
    monkeypatch,
    capsys,
    checkpoint: str,
    committed: bool,
) -> None:
    args, food_catalog, exercise_catalog = _build_args(tmp_path)
    original_food = food_catalog.read_bytes()
    original_exercise = exercise_catalog.read_bytes()

    class SimulatedInterruption(BaseException):
        pass

    def interrupt(current: str) -> None:
        if current == checkpoint:
            raise SimulatedInterruption

    monkeypatch.setattr(build_module, "_publication_checkpoint", interrupt)

    with pytest.raises(SimulatedInterruption):
        main(args)

    manifest = tmp_path / ".catalog-localization.publish.json"
    assert manifest.exists()
    interrupted_food = food_catalog.read_bytes()
    interrupted_exercise = exercise_catalog.read_bytes()

    monkeypatch.setattr(build_module, "_publication_checkpoint", lambda _phase: None)
    _argument_path(args, "--food-localization").unlink()

    assert main(args) == 4
    assert "LOCALIZATION_INVALID" in capsys.readouterr().err
    if committed:
        assert food_catalog.read_bytes() == interrupted_food
        assert exercise_catalog.read_bytes() == interrupted_exercise
        assert interrupted_food != original_food
        assert interrupted_exercise != original_exercise
    else:
        assert food_catalog.read_bytes() == original_food
        assert exercise_catalog.read_bytes() == original_exercise
    assert not manifest.exists()
    assert list(tmp_path.glob("*.catalog.next")) == []
    assert list(tmp_path.glob("*.catalog.backup")) == []


@pytest.mark.parametrize(
    ("checkpoint", "use_known_old_hash"),
    [("food_replaced", False), ("committed", True)],
)
def test_recovery_rejects_divergent_output_and_retains_recovery_state(
    tmp_path: Path,
    monkeypatch,
    capsys,
    checkpoint: str,
    use_known_old_hash: bool,
) -> None:
    args, food_catalog, _exercise_catalog = _build_args(tmp_path)
    original_food = food_catalog.read_bytes()

    class SimulatedInterruption(BaseException):
        pass

    def interrupt(current: str) -> None:
        if current == checkpoint:
            raise SimulatedInterruption

    monkeypatch.setattr(build_module, "_publication_checkpoint", interrupt)
    with pytest.raises(SimulatedInterruption):
        main(args)

    manifest = tmp_path / ".catalog-localization.publish.json"
    retained_manifest = manifest.read_bytes()
    retained_backups = {
        path: path.read_bytes() for path in tmp_path.glob("*.catalog.backup")
    }
    divergent = (
        original_food
        if use_known_old_hash
        else b"divergent external catalog bytes\n"
    )
    food_catalog.write_bytes(divergent)
    monkeypatch.setattr(build_module, "_publication_checkpoint", lambda _phase: None)

    assert main(args) == 5

    error = json.loads(capsys.readouterr().err)["error"]
    assert error["code"] == "CATALOG_RECOVERY_CONFLICT"
    assert food_catalog.read_bytes() == divergent
    assert manifest.read_bytes() == retained_manifest
    assert retained_backups
    assert all(path.read_bytes() == value for path, value in retained_backups.items())


def test_build_rejects_concurrent_writer_process(tmp_path: Path) -> None:
    args, food_catalog, exercise_catalog = _build_args(tmp_path)
    original_food = food_catalog.read_bytes()
    original_exercise = exercise_catalog.read_bytes()
    lock = tmp_path / ".catalog-localization.publish.lock"
    command = [
        sys.executable,
        str(Path(build_module.__file__).resolve()),
        *args,
    ]

    with build_module._exclusive_writer_locks((lock,)):
        completed = subprocess.run(
            command,
            cwd=Path(build_module.__file__).parents[1],
            text=True,
            capture_output=True,
            check=False,
        )

    assert completed.returncode == 5
    assert "CATALOG_BUILD_LOCKED" in completed.stderr
    assert food_catalog.read_bytes() == original_food
    assert exercise_catalog.read_bytes() == original_exercise
    assert subprocess.run(command, text=True, capture_output=True, check=False).returncode == 0


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
    cleanup_attempts: list[Path] = []
    real_unlink = Path.unlink

    def fail_replace_and_restore(path: Path, target: Path) -> Path:
        nonlocal failed_second_replace, failed_restore, retained_backup
        if (
            not failed_second_replace
            and path.name == f".{exercise_catalog.name}.catalog.next"
        ):
            failed_second_replace = True
            raise OSError("forced second replacement failure")
        if (
            failed_second_replace
            and not failed_restore
            and path.name == f".{food_catalog.name}.catalog.backup"
        ):
            failed_restore = True
            retained_backup = path
            raise OSError("forced backup restoration failure")
        return real_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_replace_and_restore)

    def fail_one_cleanup(path: Path, *args, **kwargs) -> None:
        cleanup_attempts.append(path)
        if path.name == f".{exercise_catalog.name}.catalog.next":
            raise OSError("forced cleanup failure")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_one_cleanup)

    assert main(args) == 5

    messages = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    error = messages[0]["error"]
    assert error["code"] == "CATALOG_ROLLBACK_INCOMPLETE"
    assert messages[1]["success"] is False
    assert messages[1]["diagnostic"]["code"] == "CATALOG_CLEANUP_FAILED"
    assert failed_second_replace is True
    assert failed_restore is True
    assert retained_backup is not None
    assert str(retained_backup) in error["message"]
    assert retained_backup.read_bytes() == original_food
    assert exercise_catalog.read_bytes() == original_exercise
    assert list(tmp_path.glob("*.catalog.next")) == [
        exercise_catalog.with_name(f".{exercise_catalog.name}.catalog.next")
    ]
    assert retained_backup in list(tmp_path.glob("*.catalog.backup"))
    assert (tmp_path / ".catalog-localization.publish.json").exists()
    assert (
        tmp_path / ".catalog-localization.publish.json.next"
    ) in cleanup_attempts


def test_successful_commit_reports_cleanup_failure_and_continues(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    args, food_catalog, exercise_catalog = _build_args(tmp_path)
    failed_path = food_catalog.with_name(f".{food_catalog.name}.catalog.backup")
    later_path = exercise_catalog.with_name(
        f".{exercise_catalog.name}.catalog.backup"
    )
    real_unlink = Path.unlink
    attempts: list[Path] = []

    def fail_one_cleanup(path: Path, *args, **kwargs) -> None:
        attempts.append(path)
        if path == failed_path and path.exists():
            raise OSError("forced cleanup failure")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_one_cleanup)

    assert main(args) == 0

    message = json.loads(capsys.readouterr().err)
    assert message["success"] is True
    assert message["diagnostic"]["code"] == "CATALOG_CLEANUP_FAILED"
    assert str(failed_path) in message["diagnostic"]["message"]
    assert later_path in attempts
    assert failed_path.exists()
    assert not later_path.exists()
    assert (tmp_path / ".catalog-localization.publish.json").exists()


def test_cleanup_failure_does_not_mask_publication_error(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    args, food_catalog, exercise_catalog = _build_args(tmp_path)
    original_food = food_catalog.read_bytes()
    original_exercise = exercise_catalog.read_bytes()
    exercise_next = exercise_catalog.with_name(
        f".{exercise_catalog.name}.catalog.next"
    )
    manifest_next = tmp_path / ".catalog-localization.publish.json.next"
    real_replace = Path.replace
    real_unlink = Path.unlink
    cleanup_attempts: list[Path] = []

    def fail_publication(path: Path, target: Path) -> Path:
        if path == exercise_next:
            raise OSError("forced publication failure")
        return real_replace(path, target)

    def fail_cleanup(path: Path, *args, **kwargs) -> None:
        cleanup_attempts.append(path)
        if path == exercise_next and path.exists():
            raise OSError("forced cleanup failure")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "replace", fail_publication)
    monkeypatch.setattr(Path, "unlink", fail_cleanup)

    assert main(args) == 5

    messages = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert messages[0]["error"]["code"] == "CATALOG_BUILD_FAILED"
    assert messages[1]["success"] is False
    assert messages[1]["diagnostic"]["code"] == "CATALOG_CLEANUP_FAILED"
    assert manifest_next in cleanup_attempts
    assert food_catalog.read_bytes() == original_food
    assert exercise_catalog.read_bytes() == original_exercise


def test_help_documents_windows_recovery_guarantee_boundary(capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--help"])

    assert raised.value.code == 0
    help_text = capsys.readouterr().out
    assert "process termination" in help_text
    assert "concurrent writers" in help_text
    assert "power loss or OS crashes" in help_text
    assert "does not guarantee" in help_text
    assert "metadata ordering" in help_text


def test_atomic_outputs_use_sibling_temps_fsynced_before_replacement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    args, food_catalog, exercise_catalog = _build_args(tmp_path)
    real_fsync = os.fsync
    real_replace = Path.replace
    events: list[tuple[str, object]] = []

    def record_fsync(file_descriptor: int) -> None:
        events.append(("fsync", os.fstat(file_descriptor).st_size))
        real_fsync(file_descriptor)

    def record_replace(path: Path, target: Path) -> Path:
        if path in {
            food_catalog.with_name(f".{food_catalog.name}.catalog.next"),
            exercise_catalog.with_name(f".{exercise_catalog.name}.catalog.next"),
        }:
            events.append(("replace", (path, target)))
        return real_replace(path, target)

    def record_parent_fsync(path: Path) -> None:
        events.append(("parent_fsync", path))

    monkeypatch.setattr(build_module.os, "fsync", record_fsync)
    monkeypatch.setattr(build_module, "_fsync_parent", record_parent_fsync)
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
    ) >= 5
    staged_paths = {
        food_catalog.with_name(f".{food_catalog.name}.catalog.next"),
        exercise_catalog.with_name(f".{exercise_catalog.name}.catalog.next"),
        food_catalog.with_name(f".{food_catalog.name}.catalog.backup"),
        exercise_catalog.with_name(f".{exercise_catalog.name}.catalog.backup"),
        tmp_path / ".catalog-localization.publish.json.next",
        tmp_path / ".catalog-localization.publish.json",
    }
    assert staged_paths <= {
        detail
        for event, detail in events[: replace_indexes[0]]
        if event == "parent_fsync"
    }
    for index in replace_indexes:
        temporary, output = events[index][1]
        assert temporary.parent == output.parent
        assert temporary.name == f".{output.name}.catalog.next"
