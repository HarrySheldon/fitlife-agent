from pathlib import Path

from backend.tools.catalog_receiver import main


ROOT = Path(__file__).parent
FOOD_PROFILE = Path(__file__).parents[2] / "data/catalog/mappings/tfda-foods.v1.json"


def test_inspect_and_validate_commands_emit_json(capsys) -> None:
    source = ROOT / "fixtures/tfda-foods.csv"

    inspect_exit = main(["inspect", str(source), "--catalog-kind", "food"])
    validate_exit = main(["validate", str(source), "--mapping", str(FOOD_PROFILE)])

    output = capsys.readouterr().out
    assert inspect_exit == 0
    assert validate_exit == 0
    assert '"mapping_candidates"' in output
    assert '"accepted_count": 1' in output


def test_physical_mapping_and_data_errors_have_stable_exit_codes(tmp_path: Path, capsys) -> None:
    unsupported = tmp_path / "foods.xlsx"
    unsupported.write_text("data", encoding="utf-8")
    assert main(["inspect", str(unsupported)]) == 2

    bad_mapping = tmp_path / "mapping.json"
    bad_mapping.write_text("{}", encoding="utf-8")
    assert main(["validate", str(ROOT / "fixtures/tfda-foods.csv"), "--mapping", str(bad_mapping)]) == 3

    bad_food = tmp_path / "foods.csv"
    text = (ROOT / "fixtures/tfda-foods.csv").read_text(encoding="utf-8")
    bad_food.write_text(text.replace("粗脂肪,g,0.3", "膳食纖維,g,0.3"), encoding="utf-8")
    assert main(["validate", str(bad_food), "--mapping", str(FOOD_PROFILE)]) == 4
    captured = capsys.readouterr()
    assert "SOURCE_EXTENSION_UNSUPPORTED" in captured.err
    assert "MAPPING_PROFILE_INVALID" in captured.err
    assert "REQUIRED_NUTRIENT_MISSING" in captured.out


def test_import_command_creates_database_and_skips_second_run(tmp_path: Path, capsys) -> None:
    source = ROOT / "fixtures/tfda-foods.csv"
    database = tmp_path / "catalog.sqlite3"
    args = [
        "import", str(source), "--mapping", str(FOOD_PROFILE), "--database", str(database)
    ]

    assert main(args) == 0
    assert main(args) == 0

    output = capsys.readouterr().out
    assert '"status": "committed"' in output
    assert '"status": "skipped"' in output
    assert database.exists()
