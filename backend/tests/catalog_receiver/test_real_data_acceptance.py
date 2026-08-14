import csv
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

from backend.catalog_receiver.localization import load_localization_bundle
from backend.catalog_receiver.mapping import load_mapping_profile
from backend.catalog_receiver.projectors import project_source
from backend.catalog_receiver.readers import read_source
from backend.catalog_receiver.validators import validate_records


CATALOG_ROOT = Path(__file__).parents[2] / "data" / "catalog"
FOOD_LOCALIZATION = CATALOG_ROOT / "localizations" / "tfda-foods.zh-CN.v1.json"
FOOD_MAPPING = CATALOG_ROOT / "mappings" / "tfda-foods.v1.json"
EXERCISE_LOCALIZATION = (
    CATALOG_ROOT / "localizations" / "free-exercise-db.zh-CN.v2.json"
)
EXERCISE_TAXONOMY = (
    CATALOG_ROOT / "localizations" / "exercise-taxonomy.zh-CN.v1.json"
)
EXERCISE_MAPPING = CATALOG_ROOT / "mappings" / "free-exercise-db.v1.json"
EXERCISE_SNAPSHOT = CATALOG_ROOT / "exercises.zh-CN.v1.json"


def _normalize_search_term(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _reconstruct_upstream_exercises(snapshot: dict) -> list[dict]:
    upstream: list[dict] = []
    for record in snapshot["exercises"]:
        provenance = record["provenance"]
        upstream.append(
            {
                "id": record["source_record_id"],
                "name": provenance["upstream_name"],
                "category": provenance["original_category"],
                "primaryMuscles": [record["primary_muscle"]],
                "secondaryMuscles": record["secondary_muscles"],
                "equipment": provenance["equipment"],
                "level": provenance["level"],
                "mechanic": provenance["mechanic"],
                "force": provenance["force"],
                "instructions": provenance["instructions"],
                "images": ["preserved"] * provenance["image_count"],
            }
        )
    return upstream


def test_bundled_exercise_localization_matches_complete_source_contract() -> None:
    snapshot = json.loads(EXERCISE_SNAPSHOT.read_text(encoding="utf-8"))
    raw_localization = EXERCISE_LOCALIZATION.read_bytes()
    localization = json.loads(raw_localization.decode("utf-8"))
    bundle = load_localization_bundle(
        catalog_kind="exercise",
        localization_path=EXERCISE_LOCALIZATION,
        taxonomy_path=EXERCISE_TAXONOMY,
    )
    taxonomy = bundle.taxonomy
    assert taxonomy is not None

    assert list(localization) == [
        "schema_version",
        "version",
        "source_name",
        "locale",
        "entries",
    ]
    assert localization["schema_version"] == 1
    assert localization["version"] == "2.0.0"
    assert localization["source_name"] == "free-exercise-db"
    assert localization["locale"] == "zh-CN"
    assert raw_localization == (
        json.dumps(localization, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")

    source_by_id = {
        record["source_record_id"]: record for record in snapshot["exercises"]
    }
    entries = localization["entries"]
    source_ids = sorted(source_by_id)
    assert len(source_ids) == len(entries) == 750
    assert list(entries) == source_ids
    assert set(entries) == set(source_by_id)

    expected_instruction_counts = {
        source_id: len(record["provenance"]["instructions"])
        for source_id, record in source_by_id.items()
    }
    localized_instruction_counts = {
        source_id: len(entry["instructions_zh_cn"])
        for source_id, entry in entries.items()
    }
    assert localized_instruction_counts == expected_instruction_counts
    assert sum(localized_instruction_counts.values()) == 3_388

    canonical_names = {
        _normalize_search_term(entry["name_zh_cn"]) for entry in entries.values()
    }
    alias_names = {
        _normalize_search_term(alias)
        for entry in entries.values()
        for alias in entry["aliases"]
    }
    assert len(canonical_names) == 750
    assert canonical_names.isdisjoint(alias_names)

    display_values = [
        value
        for entry in entries.values()
        for value in (entry["name_zh_cn"], *entry["instructions_zh_cn"])
    ]
    latin_tokens = Counter(
        token for value in display_values for token in re.findall(r"[A-Za-z]+", value)
    )
    assert latin_tokens == Counter({"EZ": 46, "T": 5})
    assert set(latin_tokens) <= set(taxonomy.approved_latin)

    taxonomy_contract = {
        "primary_muscle": taxonomy.muscles,
        "secondary_muscles": taxonomy.muscles,
        "equipment": taxonomy.equipment,
        "level": taxonomy.levels,
        "mechanic": taxonomy.mechanics,
        "original_category": taxonomy.categories,
    }
    for source_field, known_values in taxonomy_contract.items():
        if source_field == "primary_muscle":
            observed = {record[source_field] for record in snapshot["exercises"]}
        elif source_field == "secondary_muscles":
            observed = {
                value
                for record in snapshot["exercises"]
                for value in record[source_field]
            }
        else:
            observed = {
                record["provenance"][source_field]
                for record in snapshot["exercises"]
                if record["provenance"][source_field] is not None
            }
        assert observed <= set(known_values)


def test_bundled_exercise_localization_projects_all_source_records(
    tmp_path: Path,
) -> None:
    snapshot = json.loads(EXERCISE_SNAPSHOT.read_text(encoding="utf-8"))
    source_path = tmp_path / "free-exercise-db.json"
    source_path.write_text(
        json.dumps(_reconstruct_upstream_exercises(snapshot), ensure_ascii=False),
        encoding="utf-8",
    )
    bundle = load_localization_bundle(
        catalog_kind="exercise",
        localization_path=EXERCISE_LOCALIZATION,
        taxonomy_path=EXERCISE_TAXONOMY,
    )

    result = project_source(
        read_source(source_path),
        load_mapping_profile(EXERCISE_MAPPING),
        localization_bundle=bundle,
    )

    source_names = {
        record["source_record_id"]: record["provenance"]["upstream_name"]
        for record in snapshot["exercises"]
    }
    blocking_issues = [
        issue
        for issue in (*result.issues, *validate_records(result.records))
        if issue.severity == "error"
    ]
    assert result.scanned_count == 750
    assert len(result.records) == 750
    assert result.rejected_count == 0
    assert result.enrichment_count == 750
    assert result.enrichment_coverage == 1.0
    assert blocking_issues == []
    assert {
        record.source_record_id for record in result.records
    } == set(source_names)
    assert all(
        source_names[record.source_record_id] in record.aliases
        for record in result.records
    )


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
