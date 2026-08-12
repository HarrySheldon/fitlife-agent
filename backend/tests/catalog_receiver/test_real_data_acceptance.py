import csv
import json
from pathlib import Path

from backend.catalog_receiver.localization import load_localization_bundle
from backend.catalog_receiver.mapping import load_mapping_profile
from backend.catalog_receiver.projectors import project_source
from backend.catalog_receiver.readers import read_source


CATALOG_ROOT = Path(__file__).parents[2] / "data" / "catalog"
FOOD_LOCALIZATION = CATALOG_ROOT / "localizations" / "tfda-foods.zh-CN.v1.json"
FOOD_MAPPING = CATALOG_ROOT / "mappings" / "tfda-foods.v1.json"


def test_bundled_tfda_snapshot_contains_only_complete_foods() -> None:
    payload = json.loads((CATALOG_ROOT / "foods.zh-CN.v1.json").read_text(encoding="utf-8"))

    assert payload["source_name"] == "Taiwan FDA Food Nutrient Database"
    assert len(payload["foods"]) == 2_128
    assert all(
        record["source_name"] == payload["source_name"]
        and record["basis_type"] == "per_100g"
        and record["basis_amount"] == 100
        and record["unit"] == "g"
        and all(record[field] >= 0 for field in ("calories", "carbs", "protein", "fat"))
        and record["license"]
        and record["attribution"]
        and record["provenance"]
        for record in payload["foods"]
    )


def test_bundled_food_policy_localizes_all_normalized_names_with_sparse_overrides(
    tmp_path: Path,
) -> None:
    payload = json.loads((CATALOG_ROOT / "foods.zh-CN.v1.json").read_text(encoding="utf-8"))
    bundle = load_localization_bundle(
        catalog_kind="food",
        localization_path=FOOD_LOCALIZATION,
    )
    source_ids = {record["source_record_id"] for record in payload["foods"]}

    assert len(source_ids) == 2_128
    assert set(bundle.food_entries) <= source_ids
    assert all(entry.review_note for entry in bundle.food_entries.values())

    source_path = tmp_path / "normalized-food-policy.csv"
    headers = (
        "食品分類",
        "資料類別",
        "整合編號",
        "樣品名稱",
        "俗名",
        "樣品英文名稱",
        "內容物描述",
        "分析項分類",
        "分析項",
        "含量單位",
        "每100克含量",
    )
    nutrients = (
        ("修正熱量", "kcal", 1),
        ("總碳水化合物", "g", 1),
        ("粗蛋白", "g", 1),
        ("粗脂肪", "g", 1),
    )
    with source_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        for record in payload["foods"]:
            for nutrient, unit, amount in nutrients:
                writer.writerow(
                    (
                        "审计",
                        "样品基本资料",
                        record["source_record_id"],
                        record["name"],
                        "",
                        "",
                        "",
                        "一般成分",
                        nutrient,
                        unit,
                        amount,
                    )
                )

    result = project_source(
        read_source(source_path),
        load_mapping_profile(FOOD_MAPPING),
        localization_bundle=bundle,
    )

    assert result.rejected_count == 0
    assert len(result.records) == 2_128
    assert {record.source_record_id for record in result.records} == source_ids
    assert {record.provenance["localization"]["method"] for record in result.records} == {
        "glossary",
        "opencc_tw2sp",
        "record_override",
    }


def test_bundled_exercise_snapshot_excludes_stretching_without_met_invention() -> None:
    payload = json.loads((CATALOG_ROOT / "exercises.zh-CN.v1.json").read_text(encoding="utf-8"))

    assert payload["managed_sources"] == ["free-exercise-db"]
    assert len(payload["exercises"]) == 750
    assert {record["exercise_type"] for record in payload["exercises"]} == {
        "strength",
        "cardio",
    }
    assert all(
        record["provenance"]["original_category"] != "stretching"
        and record["met"] is None
        and record["license"] == "Unlicense"
        for record in payload["exercises"]
    )
