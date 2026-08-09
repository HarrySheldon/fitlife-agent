from pathlib import Path

from scripts.import_initial_catalogs import main


ROOT = Path(__file__).parent


def test_initial_script_imports_both_sources_and_is_idempotent(tmp_path: Path, capsys) -> None:
    args = [
        "--foods", str(ROOT / "fixtures/tfda-foods.csv"),
        "--exercises", str(ROOT / "fixtures/free-exercises.json"),
        "--exercise-aliases", str(ROOT / "fixtures/free-exercises.zh-CN.json"),
        "--database", str(tmp_path / "catalog.sqlite3"),
        "--output-dir", str(tmp_path / "reports"),
    ]

    assert main(args) == 0
    assert main(args) == 0

    output = capsys.readouterr().out
    assert '"status": "committed"' in output
    assert '"status": "skipped"' in output
    assert (tmp_path / "reports/foods/normalized-foods.json").exists()
    assert (tmp_path / "reports/exercises/normalized-exercises.json").exists()


def test_initial_script_validates_both_before_creating_database(tmp_path: Path) -> None:
    bad_food = tmp_path / "bad-food.csv"
    text = (ROOT / "fixtures/tfda-foods.csv").read_text(encoding="utf-8")
    bad_food.write_text(text.replace("粗脂肪,g,0.3", "膳食纖維,g,0.3"), encoding="utf-8")
    database = tmp_path / "must-not-exist.sqlite3"

    exit_code = main(
        [
            "--foods", str(bad_food),
            "--exercises", str(ROOT / "fixtures/free-exercises.json"),
            "--exercise-aliases", str(ROOT / "fixtures/free-exercises.zh-CN.json"),
            "--database", str(database),
            "--output-dir", str(tmp_path / "reports"),
        ]
    )

    assert exit_code == 4
    assert not database.exists()
    assert (tmp_path / "reports/exercises/catalog-import-report.json").exists()
