import json
from pathlib import Path

from backend.catalog_receiver.localization import load_localization_bundle
from backend.catalog_receiver.mapping import load_mapping_profile
from backend.catalog_receiver.projectors import project_source
from backend.catalog_receiver.readers import read_source
from backend.catalog_receiver.validators import enrich_issue


ROOT = Path(__file__).parent
FOOD_LOCALIZATION = ROOT / "fixtures" / "food-localization.zh-CN.json"
CATALOG_LOCALIZATION = (
    Path(__file__).parents[2]
    / "data"
    / "catalog"
    / "localizations"
    / "tfda-foods.zh-CN.v1.json"
)


def _food_localization(
    tmp_path: Path,
    *,
    name: str,
    review_note: str | None = None,
    source_id: str = "A001",
) -> Path:
    entry: dict[str, object] = {"name_zh_cn": name, "aliases": []}
    if review_note is not None:
        entry["review_note"] = review_note
    path = tmp_path / f"food-localization-{len(list(tmp_path.iterdir()))}.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "version": "test",
                "source_name": "Taiwan FDA Food Nutrient Database",
                "locale": "zh-CN",
                "entries": {source_id: entry},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_projects_grouped_tfda_nutrients_and_preserves_aliases() -> None:
    source = read_source(ROOT / "fixtures" / "tfda-foods.csv")
    profile = load_mapping_profile(
        Path(__file__).parents[2] / "data" / "catalog" / "mappings" / "tfda-foods.v1.json"
    )
    localization = load_localization_bundle(
        catalog_kind="food",
        localization_path=FOOD_LOCALIZATION,
    )

    result = project_source(source, profile, localization_bundle=localization)

    assert result.scanned_count == 1
    assert result.rejected_count == 0
    food = result.records[0]
    assert food.source_record_id == "A001"
    assert food.name == "米饭"
    assert food.aliases == ("白飯", "白饭", "米飯", "Cooked rice")
    assert (food.calories, food.carbs, food.protein, food.fat) == (130, 28.2, 2.7, 0.3)
    assert food.basis_type == "per_100g"
    assert food.provenance["name_conversion"] == "opencc_tw2sp"
    assert food.provenance["localization"] == {
        "locale": "zh-CN",
        "asset_version": "1.0.0",
        "upstream_name": "白飯",
        "method": "glossary",
    }


def test_bundled_food_localization_contains_mainland_glossary_and_reviewed_override() -> None:
    bundle = load_localization_bundle(
        catalog_kind="food",
        localization_path=CATALOG_LOCALIZATION,
    )

    localized_names = {entry.name_zh_cn for entry in bundle.food_entries.values()}
    assert {"米饭", "金枪鱼肚", "土豆", "西兰花芽", "猕猴桃", "菠萝酥"} <= localized_names
    override = bundle.food("D1200201")
    assert override.name_zh_cn == "凤梨释迦"
    assert override.review_note


def test_food_localization_precedence_is_override_then_glossary_then_tw2sp(
    tmp_path: Path,
) -> None:
    fixture = (ROOT / "fixtures" / "tfda-foods.csv").read_text(encoding="utf-8")
    profile = load_mapping_profile(
        Path(__file__).parents[2] / "data" / "catalog" / "mappings" / "tfda-foods.v1.json"
    )

    def project_name(
        traditional_name: str,
        localized_name: str,
        review_note: str | None = None,
        source_id: str = "A001",
    ) -> tuple[str, str]:
        source_path = tmp_path / f"foods-{traditional_name}.csv"
        source_path.write_text(fixture.replace("白飯", traditional_name), encoding="utf-8")
        bundle = load_localization_bundle(
            catalog_kind="food",
            localization_path=_food_localization(
                tmp_path,
                name=localized_name,
                review_note=review_note,
                source_id=source_id,
            ),
        )
        result = project_source(
            read_source(source_path),
            profile,
            localization_bundle=bundle,
        )
        food = result.records[0]
        return food.name, food.provenance["localization"]["method"]

    assert project_name("臺灣米", "未使用", source_id="A999") == (
        "台湾米",
        "opencc_tw2sp",
    )
    assert project_name("白飯", "米饭") == ("米饭", "glossary")
    assert project_name("白飯", "家常米饭", "Distinguishes this reviewed record.") == (
        "家常米饭",
        "record_override",
    )


def test_rejects_food_record_override_without_review_note(tmp_path: Path) -> None:
    profile = load_mapping_profile(
        Path(__file__).parents[2] / "data" / "catalog" / "mappings" / "tfda-foods.v1.json"
    )
    bundle = load_localization_bundle(
        catalog_kind="food",
        localization_path=_food_localization(tmp_path, name="家常米饭"),
    )

    result = project_source(
        read_source(ROOT / "fixtures" / "tfda-foods.csv"),
        profile,
        localization_bundle=bundle,
    )

    assert result.records == ()
    assert result.rejected_count == 1
    issue = enrich_issue(result.issues[0])
    assert issue.code == "LOCALIZATION_OVERRIDE_REVIEW_NOTE_MISSING"
    assert issue.message == "A record-specific food localization override lacks a review note."


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
