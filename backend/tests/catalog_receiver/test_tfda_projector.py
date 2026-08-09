from pathlib import Path

from backend.catalog_receiver.mapping import load_mapping_profile
from backend.catalog_receiver.projectors import project_source
from backend.catalog_receiver.readers import read_source


ROOT = Path(__file__).parent


def test_projects_grouped_tfda_nutrients_and_preserves_aliases() -> None:
    source = read_source(ROOT / "fixtures" / "tfda-foods.csv")
    profile = load_mapping_profile(
        Path(__file__).parents[2] / "data" / "catalog" / "mappings" / "tfda-foods.v1.json"
    )

    result = project_source(source, profile)

    assert result.scanned_count == 1
    assert result.rejected_count == 0
    food = result.records[0]
    assert food.source_record_id == "A001"
    assert food.name == "白饭"
    assert food.aliases == ("白飯", "米飯", "Cooked rice")
    assert (food.calories, food.carbs, food.protein, food.fat) == (130, 28.2, 2.7, 0.3)
    assert food.basis_type == "per_100g"
    assert food.provenance["name_conversion"] == "opencc_t2s"


def test_rejects_inconsistent_group_and_missing_nutrient(tmp_path: Path) -> None:
    fixture = (ROOT / "fixtures" / "tfda-foods.csv").read_text(encoding="utf-8")
    fixture = fixture.replace("白飯,米飯", "另一名稱,米飯", 1).replace(
        "一般成分,粗脂肪,g,0.3", "一般成分,膳食纖維,g,0.3"
    )
    path = tmp_path / "bad.csv"
    path.write_text(fixture, encoding="utf-8")
    profile = load_mapping_profile(
        Path(__file__).parents[2] / "data" / "catalog" / "mappings" / "tfda-foods.v1.json"
    )

    strict = profile.model_copy(
        update={
            "projection": profile.projection.model_copy(
                update={"exclude_incomplete_groups": False}
            )
        }
    )
    result = project_source(read_source(path), strict)

    assert result.records == ()
    assert {issue.code for issue in result.issues} == {
        "GROUP_DESCRIPTOR_INCONSISTENT",
        "REQUIRED_NUTRIENT_MISSING",
    }


def test_profile_explicitly_excludes_incomplete_nutrition(tmp_path: Path) -> None:
    fixture = (ROOT / "fixtures" / "tfda-foods.csv").read_text(encoding="utf-8")
    path = tmp_path / "incomplete.csv"
    path.write_text(
        fixture.replace("一般成分,粗脂肪,g,0.3", "一般成分,粗脂肪,g,"),
        encoding="utf-8",
    )
    profile = load_mapping_profile(
        Path(__file__).parents[2] / "data" / "catalog" / "mappings" / "tfda-foods.v1.json"
    )

    result = project_source(read_source(path), profile)

    assert result.records == ()
    assert result.excluded_count == 1
    assert result.rejected_count == 0
    assert result.issues[0].severity == "info"
    assert result.issues[0].code == "FOOD_GROUP_EXCLUDED_INCOMPLETE_NUTRITION"


def test_rejects_bad_number_and_unit(tmp_path: Path) -> None:
    fixture = (ROOT / "fixtures" / "tfda-foods.csv").read_text(encoding="utf-8")
    fixture = fixture.replace("總碳水化合物,g,28.2", "總碳水化合物,mg,unknown")
    path = tmp_path / "bad.csv"
    path.write_text(fixture, encoding="utf-8")
    profile = load_mapping_profile(
        Path(__file__).parents[2] / "data" / "catalog" / "mappings" / "tfda-foods.v1.json"
    )

    result = project_source(read_source(path), profile)

    assert {issue.code for issue in result.issues} == {
        "NUTRIENT_UNIT_UNSUPPORTED",
        "VALUE_NUMBER_INVALID",
    }
