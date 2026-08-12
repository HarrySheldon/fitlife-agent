import json
from pathlib import Path

from scripts.import_initial_catalogs import main


ROOT = Path(__file__).parent
MAPPINGS = Path(__file__).parents[2] / "data" / "catalog" / "mappings"


def _legacy_mapping_root(tmp_path: Path) -> Path:
    mapping_root = tmp_path / "mappings"
    mapping_root.mkdir()
    for name in ("tfda-foods.v1.json", "free-exercise-db.v1.json"):
        payload = json.loads((MAPPINGS / name).read_text(encoding="utf-8"))
        if name == "free-exercise-db.v1.json":
            payload["enrichment"]["minimum_coverage"] = 0
        (mapping_root / name).write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    return mapping_root


def test_initial_script_imports_both_sources_and_is_idempotent(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "scripts.import_initial_catalogs.MAPPING_ROOT",
        _legacy_mapping_root(tmp_path),
    )
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
    bad_food.write_text(text.replace("總碳水化合物,g,28.2", "總碳水化合物,mg,unknown"), encoding="utf-8")
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
