import json
from pathlib import Path

import pytest

from backend.catalog_receiver.localization import load_localization_bundle
from backend.catalog_receiver.mapping import load_mapping_profile
from backend.catalog_receiver.models import FieldSpec, ReceiverError
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
FOOD_GLOSSARY = (
    {
        "source": "红马铃薯(粉红珍珠马铃薯)",
        "target": "红土豆(粉红珍珠土豆)",
        "match_mode": "exact",
        "priority": 10,
    },
    {
        "source": "小马铃薯(珍珠马铃薯)",
        "target": "小土豆(珍珠土豆)",
        "match_mode": "exact",
        "priority": 20,
    },
    {"source": "白饭", "target": "米饭", "match_mode": "exact", "priority": 30},
    {"source": "鲔鱼", "target": "金枪鱼", "match_mode": "contains", "priority": 40},
    {"source": "马铃薯", "target": "土豆", "match_mode": "contains", "priority": 50},
    {"source": "青花菜", "target": "西兰花", "match_mode": "prefix", "priority": 60},
    {"source": "青花菜", "target": "西兰花", "match_mode": "suffix", "priority": 70},
    {"source": "奇异果", "target": "猕猴桃", "match_mode": "suffix", "priority": 80},
    {"source": "凤梨", "target": "菠萝", "match_mode": "prefix", "priority": 90},
    {"source": "凤梨", "target": "菠萝", "match_mode": "suffix", "priority": 100},
)


def _food_localization(
    tmp_path: Path,
    *,
    name: str | None = None,
    review_note: str | None = None,
    source_id: str = "A001",
    aliases: tuple[str, ...] = (),
    glossary: tuple[dict[str, object], ...] | None = None,
) -> Path:
    entries: dict[str, object] = {}
    if name is not None:
        entry: dict[str, object] = {"name_zh_cn": name, "aliases": aliases}
        if review_note is not None:
            entry["review_note"] = review_note
        entries[source_id] = entry
    path = tmp_path / f"food-localization-{len(list(tmp_path.iterdir()))}.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "version": "test",
                "source_name": "Taiwan FDA Food Nutrient Database",
                "locale": "zh-CN",
                "glossary": glossary if glossary is not None else FOOD_GLOSSARY,
                "entries": entries,
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
        localization_path=CATALOG_LOCALIZATION,
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
        "asset_version": "1.3.1",
        "upstream_name": "白飯",
        "method": "glossary",
    }


def test_no_bundle_preserves_profile_resolved_name() -> None:
    profile = load_mapping_profile(
        Path(__file__).parents[2] / "data" / "catalog" / "mappings" / "tfda-foods.v1.json"
    )
    fields = dict(profile.projection.fields)
    fields["name"] = FieldSpec(constant="映射专用名称")
    custom_profile = profile.model_copy(
        update={"projection": profile.projection.model_copy(update={"fields": fields})}
    )

    result = project_source(
        read_source(ROOT / "fixtures" / "tfda-foods.csv"),
        custom_profile,
    )

    assert result.records[0].name == "映射专用名称"
    assert result.records[0].provenance["name_conversion"] is None


@pytest.mark.parametrize(
    ("bundle_update", "field"),
    [
        ({"catalog_kind": "exercise"}, "catalog_kind"),
        ({"source_name": "another-food-source"}, "source_name"),
    ],
)
def test_rejects_localization_bundle_that_does_not_match_profile(
    bundle_update: dict[str, str],
    field: str,
) -> None:
    profile = load_mapping_profile(
        Path(__file__).parents[2] / "data" / "catalog" / "mappings" / "tfda-foods.v1.json"
    )
    bundle = load_localization_bundle(
        catalog_kind="food",
        localization_path=FOOD_LOCALIZATION,
    ).model_copy(update=bundle_update)

    with pytest.raises(ReceiverError) as raised:
        project_source(
            read_source(ROOT / "fixtures" / "tfda-foods.csv"),
            profile,
            localization_bundle=bundle,
        )

    assert raised.value.code == "LOCALIZATION_INVALID"
    assert raised.value.issue is not None
    assert raised.value.issue.field == field


def test_bundled_food_localization_contains_mainland_glossary_and_reviewed_override() -> None:
    bundle = load_localization_bundle(
        catalog_kind="food",
        localization_path=CATALOG_LOCALIZATION,
    )

    assert bundle.version == "1.3.1"
    assert {rule.target for rule in bundle.food_glossary} >= {
        "米饭",
        "金枪鱼",
        "土豆",
        "西兰花",
        "猕猴桃",
        "菠萝",
    }
    assert tuple(rule.model_dump() for rule in bundle.food_glossary) == FOOD_GLOSSARY
    assert tuple(bundle.food_entries) == ("A0550601", "D1200201")
    rice_override = bundle.food("A0550601")
    assert rice_override.name_zh_cn == "米饭"
    assert rice_override.aliases == ("米飯",)
    assert rice_override.review_note
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
        localized_name: str | None = None,
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

    assert project_name("臺灣米") == (
        "台湾米",
        "opencc_tw2sp",
    )
    assert project_name("白飯") == ("米饭", "glossary")
    assert project_name("白飯", "家常米饭", "Distinguishes this reviewed record.") == (
        "家常米饭",
        "record_override",
    )


def test_configured_food_localization_falls_back_for_unlisted_source_id(
    tmp_path: Path,
) -> None:
    profile = load_mapping_profile(
        Path(__file__).parents[2] / "data" / "catalog" / "mappings" / "tfda-foods.v1.json"
    )
    bundle = load_localization_bundle(
        catalog_kind="food",
        localization_path=_food_localization(tmp_path),
    )

    result = project_source(
        read_source(ROOT / "fixtures" / "tfda-foods.csv"),
        profile,
        localization_bundle=bundle,
    )

    assert result.rejected_count == 0
    assert result.records[0].name == "米饭"
    assert result.records[0].provenance["localization"]["method"] == "glossary"


def test_reviewed_override_prevents_contextual_glossary_replacement(tmp_path: Path) -> None:
    fixture = (ROOT / "fixtures" / "tfda-foods.csv").read_text(encoding="utf-8")
    source_path = tmp_path / "atemoya.csv"
    source_path.write_text(
        fixture.replace("A001", "D1200201").replace("白飯", "鳳梨釋迦"),
        encoding="utf-8",
    )
    profile = load_mapping_profile(
        Path(__file__).parents[2] / "data" / "catalog" / "mappings" / "tfda-foods.v1.json"
    )
    bundle = load_localization_bundle(
        catalog_kind="food",
        localization_path=CATALOG_LOCALIZATION,
    )

    result = project_source(
        read_source(source_path),
        profile,
        localization_bundle=bundle,
    )

    food = result.records[0]
    assert food.name == "凤梨释迦"
    assert "菠萝释迦" not in food.aliases
    assert food.provenance["localization"]["method"] == "record_override"


def test_food_glossary_prefers_longest_parsed_name_term(tmp_path: Path) -> None:
    fixture = (ROOT / "fixtures" / "tfda-foods.csv").read_text(encoding="utf-8")
    source_path = tmp_path / "parsed-term.csv"
    source_path.write_text(fixture.replace("白飯", "鳳梨釋迦"), encoding="utf-8")
    profile = load_mapping_profile(
        Path(__file__).parents[2] / "data" / "catalog" / "mappings" / "tfda-foods.v1.json"
    )
    bundle = load_localization_bundle(
        catalog_kind="food",
        localization_path=_food_localization(
            tmp_path,
            glossary=(
                {
                    "source": "凤梨",
                    "target": "菠萝",
                    "match_mode": "prefix",
                    "priority": 20,
                },
                {
                    "source": "凤梨释迦",
                    "target": "番荔枝",
                    "match_mode": "exact",
                    "priority": 10,
                },
            ),
        ),
    )

    result = project_source(
        read_source(source_path),
        profile,
        localization_bundle=bundle,
    )

    food = result.records[0]
    assert food.name == "番荔枝"
    assert food.provenance["localization"]["method"] == "glossary"


@pytest.mark.parametrize(
    ("source_id", "traditional_name", "expected_name"),
    [
        ("B0700101", "紅馬鈴薯(粉紅珍珠馬鈴薯)", "红土豆(粉红珍珠土豆)"),
        ("B0700301", "小馬鈴薯(珍珠馬鈴薯)", "小土豆(珍珠土豆)"),
        ("R4100401", "冷凍馬鈴薯條", "冷冻土豆条"),
        ("R6900101", "香筍鮪魚罐頭", "香笋金枪鱼罐头"),
        ("Q0500501", "鳳梨酥", "菠萝酥"),
        ("D1100203", "金鑽鳳梨", "金钻菠萝"),
    ],
)
def test_food_glossary_localizes_compound_name_terms(
    tmp_path: Path,
    source_id: str,
    traditional_name: str,
    expected_name: str,
) -> None:
    fixture = (ROOT / "fixtures" / "tfda-foods.csv").read_text(encoding="utf-8")
    source_path = tmp_path / f"{source_id}.csv"
    source_path.write_text(
        fixture.replace("A001", source_id).replace("白飯", traditional_name),
        encoding="utf-8",
    )
    profile = load_mapping_profile(
        Path(__file__).parents[2] / "data" / "catalog" / "mappings" / "tfda-foods.v1.json"
    )
    bundle = load_localization_bundle(
        catalog_kind="food",
        localization_path=CATALOG_LOCALIZATION,
    )

    result = project_source(
        read_source(source_path),
        profile,
        localization_bundle=bundle,
    )

    food = result.records[0]
    assert food.name == expected_name
    assert food.provenance["localization"]["method"] == "glossary"


def test_food_glossary_does_not_cascade_rules(tmp_path: Path) -> None:
    fixture = (ROOT / "fixtures" / "tfda-foods.csv").read_text(encoding="utf-8")
    source_path = tmp_path / "no-cascade.csv"
    source_path.write_text(fixture.replace("白飯", "馬鈴薯"), encoding="utf-8")
    profile = load_mapping_profile(
        Path(__file__).parents[2] / "data" / "catalog" / "mappings" / "tfda-foods.v1.json"
    )
    bundle = load_localization_bundle(
        catalog_kind="food",
        localization_path=_food_localization(
            tmp_path,
            glossary=(
                {
                    "source": "马铃薯",
                    "target": "土豆",
                    "match_mode": "exact",
                    "priority": 10,
                },
                {
                    "source": "土豆",
                    "target": "豆子",
                    "match_mode": "exact",
                    "priority": 20,
                },
            ),
        ),
    )

    result = project_source(
        read_source(source_path),
        profile,
        localization_bundle=bundle,
    )

    assert result.records[0].name == "土豆"


def test_food_glossary_replaces_all_non_overlapping_contains_occurrences(
    tmp_path: Path,
) -> None:
    fixture = (ROOT / "fixtures" / "tfda-foods.csv").read_text(encoding="utf-8")
    source_path = tmp_path / "one-occurrence.csv"
    source_path.write_text(fixture.replace("白飯", "馬鈴薯馬鈴薯"), encoding="utf-8")
    profile = load_mapping_profile(
        Path(__file__).parents[2] / "data" / "catalog" / "mappings" / "tfda-foods.v1.json"
    )
    bundle = load_localization_bundle(
        catalog_kind="food",
        localization_path=_food_localization(
            tmp_path,
            glossary=(
                {
                    "source": "马铃薯",
                    "target": "土豆",
                    "match_mode": "contains",
                    "priority": 10,
                },
            ),
        ),
    )

    result = project_source(
        read_source(source_path),
        profile,
        localization_bundle=bundle,
    )

    assert result.records[0].name == "土豆土豆"


def test_food_glossary_uses_priority_for_equal_specificity_rules(tmp_path: Path) -> None:
    fixture = (ROOT / "fixtures" / "tfda-foods.csv").read_text(encoding="utf-8")
    source_path = tmp_path / "stable-order.csv"
    source_path.write_text(fixture.replace("白飯", "鳳梨酥"), encoding="utf-8")
    profile = load_mapping_profile(
        Path(__file__).parents[2] / "data" / "catalog" / "mappings" / "tfda-foods.v1.json"
    )
    bundle = load_localization_bundle(
        catalog_kind="food",
        localization_path=_food_localization(
            tmp_path,
            glossary=(
                {
                    "source": "凤梨",
                    "target": "菠萝",
                    "match_mode": "prefix",
                    "priority": 20,
                },
                {
                    "source": "凤梨",
                    "target": "黄梨",
                    "match_mode": "contains",
                    "priority": 10,
                },
            ),
        ),
    )

    result = project_source(
        read_source(source_path),
        profile,
        localization_bundle=bundle,
    )

    assert result.records[0].name == "黄梨酥"


def test_food_alias_merge_dedupes_nfkc_casefold_and_removes_canonical(
    tmp_path: Path,
) -> None:
    fixture = (ROOT / "fixtures" / "tfda-foods.csv").read_text(encoding="utf-8")
    source_path = tmp_path / "compatibility-aliases.csv"
    source_path.write_text(
        fixture.replace("白飯", "神").replace("米飯", "神").replace("Cooked rice", "ＴＥＳＴ"),
        encoding="utf-8",
    )
    profile = load_mapping_profile(
        Path(__file__).parents[2] / "data" / "catalog" / "mappings" / "tfda-foods.v1.json"
    )
    bundle = load_localization_bundle(
        catalog_kind="food",
        localization_path=_food_localization(
            tmp_path,
            name="神",
            review_note="Context-specific reviewed canonical name.",
            aliases=("test",),
            glossary=(),
        ),
    )

    result = project_source(
        read_source(source_path),
        profile,
        localization_bundle=bundle,
    )

    assert result.records[0].aliases == ("ＴＥＳＴ",)


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
