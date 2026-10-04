import json
from pathlib import Path

from scripts.import_initial_catalogs import build_parser, main


ROOT = Path(__file__).parent


def test_initial_import_parser_requires_explicit_localization_assets() -> None:
    args = build_parser().parse_args(
        [
            "--foods",
            "foods.csv",
            "--food-localization",
            "foods.zh-CN.json",
            "--exercises",
            "exercises.json",
            "--exercise-localization",
            "exercises.zh-CN.json",
            "--exercise-taxonomy",
            "taxonomy.zh-CN.json",
        ]
    )

    assert args.food_localization == Path("foods.zh-CN.json")
    assert args.exercise_localization == Path("exercises.zh-CN.json")
    assert args.exercise_taxonomy == Path("taxonomy.zh-CN.json")
    assert not hasattr(args, "exercise_aliases")


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def _localized_inputs(tmp_path: Path) -> dict[str, Path]:
    source = json.loads(
        (ROOT / "fixtures/free-exercises.json").read_text(encoding="utf-8")
    )
    exercise_source = _write_json(tmp_path / "exercises.json", [source[0]])
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
                    "aliases": ["白飯", "Cooked rice"],
                    "review_note": "Approved fixture override.",
                }
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
                    "aliases": ["Barbell Full Squat", "深蹲"],
                    "instructions_zh_cn": ["将杠铃置于上背部。", "屈髋屈膝下蹲。"],
                }
            },
        },
    )
    exercise_taxonomy = _write_json(
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
    return {
        "exercises": exercise_source,
        "food_localization": food_localization,
        "exercise_localization": exercise_localization,
        "exercise_taxonomy": exercise_taxonomy,
    }


def _import_args(tmp_path: Path, *, foods: Path) -> list[str]:
    paths = _localized_inputs(tmp_path)
    return [
        "--foods", str(foods),
        "--food-localization", str(paths["food_localization"]),
        "--exercises", str(paths["exercises"]),
        "--exercise-localization", str(paths["exercise_localization"]),
        "--exercise-taxonomy", str(paths["exercise_taxonomy"]),
        "--database", str(tmp_path / "catalog.sqlite3"),
        "--output-dir", str(tmp_path / "reports"),
    ]


def test_initial_script_imports_both_sources_and_is_idempotent(
    tmp_path: Path,
    capsys,
) -> None:
    args = _import_args(tmp_path, foods=ROOT / "fixtures/tfda-foods.csv")

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
    args = _import_args(tmp_path, foods=bad_food)
    database = tmp_path / "catalog.sqlite3"

    exit_code = main(args)

    assert exit_code == 4
    assert not database.exists()
    assert (tmp_path / "reports/exercises/catalog-import-report.json").exists()
