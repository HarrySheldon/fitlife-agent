import json
from pathlib import Path

from backend.tools.catalog_receiver import build_parser, main


ROOT = Path(__file__).parent
FOOD_PROFILE = Path(__file__).parents[2] / "data/catalog/mappings/tfda-foods.v1.json"


def _food_localization(tmp_path: Path, *, include_orphan: bool = False) -> Path:
    entries = {
        "A001": {
            "name_zh_cn": "米饭",
            "aliases": ["白飯", "Cooked rice"],
            "review_note": "Approved fixture override.",
        }
    }
    if include_orphan:
        entries["A999"] = {
            "name_zh_cn": "孤立食品",
            "review_note": "Intentional orphan fixture.",
        }
    path = tmp_path / "food-localization.zh-CN.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "version": "1.0.0",
                "source_name": "Taiwan FDA Food Nutrient Database",
                "locale": "zh-CN",
                "glossary": [],
                "entries": entries,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_validate_parser_accepts_repeatable_localizations_and_optional_taxonomy() -> None:
    args = build_parser().parse_args(
        [
            "validate",
            str(ROOT / "fixtures/tfda-foods.csv"),
            "--mapping",
            str(FOOD_PROFILE),
            "--localization",
            "food.zh-CN.json",
            "--localization",
            "shared.zh-CN.json",
            "--taxonomy",
            "taxonomy.zh-CN.json",
        ]
    )

    assert args.localizations == [Path("food.zh-CN.json"), Path("shared.zh-CN.json")]
    assert args.taxonomy == Path("taxonomy.zh-CN.json")


def test_validate_without_localization_returns_data_error(capsys) -> None:
    exit_code = main(
        [
            "validate",
            str(ROOT / "fixtures/tfda-foods.csv"),
            "--mapping",
            str(FOOD_PROFILE),
        ]
    )

    assert exit_code == 4
    assert "LOCALIZATION_MISSING" in capsys.readouterr().err


def test_food_localization_orphan_is_reported_and_blocks_output(
    tmp_path: Path,
    capsys,
) -> None:
    output_dir = tmp_path / "output"

    exit_code = main(
        [
            "validate",
            str(ROOT / "fixtures/tfda-foods.csv"),
            "--mapping",
            str(FOOD_PROFILE),
            "--localization",
            str(_food_localization(tmp_path, include_orphan=True)),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 4
    assert "LOCALIZATION_ORPHAN" in capsys.readouterr().out
    assert not (output_dir / "normalized-foods.json").exists()


def test_inspect_and_validate_commands_emit_json(
    tmp_path: Path,
    capsys,
) -> None:
    source = ROOT / "fixtures/tfda-foods.csv"
    localization = _food_localization(tmp_path)
    output_dir = tmp_path / "output"

    inspect_exit = main(["inspect", str(source), "--catalog-kind", "food"])
    validate_exit = main(
        [
            "validate",
            str(source),
            "--mapping",
            str(FOOD_PROFILE),
            "--localization",
            str(localization),
            "--output-dir",
            str(output_dir),
        ]
    )

    output = capsys.readouterr().out
    normalized = json.loads(
        (output_dir / "normalized-foods.json").read_text(encoding="utf-8")
    )
    assert inspect_exit == 0
    assert validate_exit == 0
    assert '"mapping_candidates"' in output
    assert '"accepted_count": 1' in output
    assert normalized["foods"][0]["name"] == "米饭"
    assert normalized["foods"][0]["provenance"]["localization"]["upstream_name"] == "白飯"


def test_physical_mapping_and_data_errors_have_stable_exit_codes(tmp_path: Path, capsys) -> None:
    localization = _food_localization(tmp_path)
    unsupported = tmp_path / "foods.xlsx"
    unsupported.write_text("data", encoding="utf-8")
    assert main(["inspect", str(unsupported)]) == 2

    bad_mapping = tmp_path / "mapping.json"
    bad_mapping.write_text("{}", encoding="utf-8")
    assert main(
        [
            "validate",
            str(ROOT / "fixtures/tfda-foods.csv"),
            "--mapping",
            str(bad_mapping),
            "--localization",
            str(localization),
        ]
    ) == 3

    bad_food = tmp_path / "foods.csv"
    text = (ROOT / "fixtures/tfda-foods.csv").read_text(encoding="utf-8")
    bad_food.write_text(text.replace("總碳水化合物,g,28.2", "總碳水化合物,mg,unknown"), encoding="utf-8")
    assert main(
        [
            "validate",
            str(bad_food),
            "--mapping",
            str(FOOD_PROFILE),
            "--localization",
            str(localization),
        ]
    ) == 4
    captured = capsys.readouterr()
    assert "SOURCE_EXTENSION_UNSUPPORTED" in captured.err
    assert "MAPPING_PROFILE_INVALID" in captured.err
    assert "NUTRIENT_UNIT_UNSUPPORTED" in captured.out


def test_import_command_creates_database_and_skips_second_run(tmp_path: Path, capsys) -> None:
    source = ROOT / "fixtures/tfda-foods.csv"
    database = tmp_path / "catalog.sqlite3"
    localization = _food_localization(tmp_path)
    args = [
        "import", str(source), "--mapping", str(FOOD_PROFILE),
        "--localization", str(localization), "--database", str(database)
    ]

    assert main(args) == 0
    assert main(args) == 0

    output = capsys.readouterr().out
    assert '"status": "committed"' in output
    assert '"status": "skipped"' in output
    assert database.exists()


def test_import_validation_failure_does_not_create_database(tmp_path: Path) -> None:
    source = tmp_path / "invalid.csv"
    text = (ROOT / "fixtures/tfda-foods.csv").read_text(encoding="utf-8")
    source.write_text(
        text.replace("總碳水化合物,g,28.2", "總碳水化合物,mg,unknown"),
        encoding="utf-8",
    )
    database = tmp_path / "must-not-exist.sqlite3"
    localization = _food_localization(tmp_path)

    exit_code = main(
        [
            "import",
            str(source),
            "--mapping",
            str(FOOD_PROFILE),
            "--localization",
            str(localization),
            "--database",
            str(database),
        ]
    )

    assert exit_code == 4
    assert not database.exists()
