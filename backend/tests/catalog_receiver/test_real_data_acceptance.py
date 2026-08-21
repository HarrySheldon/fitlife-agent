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
FOOD_SNAPSHOT = CATALOG_ROOT / "foods.zh-CN.v1.json"
EXERCISE_SNAPSHOT = CATALOG_ROOT / "exercises.zh-CN.v1.json"


def _normalize_search_term(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _reconstruct_upstream_exercises(snapshot: dict) -> list[dict]:
    upstream: list[dict] = []
    for record in snapshot["exercises"]:
        provenance = record["provenance"]
        preserved = provenance["upstream"]
        upstream.append(
            {
                "id": record["source_record_id"],
                "name": provenance["upstream_name"],
                "category": provenance["original_category"],
                "primaryMuscles": [preserved["primary_muscle"]],
                "secondaryMuscles": preserved["secondary_muscles"],
                "equipment": preserved["equipment"],
                "level": preserved["level"],
                "mechanic": preserved["mechanic"],
                "force": preserved["force"],
                "instructions": preserved["instructions"],
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

    full_squat = entries["Barbell_Full_Squat"]
    standard_squat = entries["Barbell_Squat"]
    assert full_squat["name_zh_cn"] == "杠铃深蹲"
    assert {"杠铃全蹲", "杠铃深蹲到底"} <= set(full_squat["aliases"])
    assert standard_squat["name_zh_cn"] == "杠铃标准深蹲"
    assert "标准杠铃深蹲" in standard_squat["aliases"]
    assert "杠铃深蹲" not in standard_squat["aliases"]
    assert "hamstrings are on your calves" in source_by_id[
        "Barbell_Full_Squat"
    ]["provenance"]["upstream"]["instructions"][3]
    assert "slightly less than 90-degrees" in source_by_id[
        "Barbell_Squat"
    ]["provenance"]["upstream"]["instructions"][3]

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
            observed = {
                record["provenance"]["upstream"][source_field]
                for record in snapshot["exercises"]
            }
        elif source_field == "secondary_muscles":
            observed = {
                value
                for record in snapshot["exercises"]
                for value in record["provenance"]["upstream"][source_field]
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
    upstream = _reconstruct_upstream_exercises(snapshot)
    source_path = tmp_path / "free-exercise-db.json"
    source_path.write_text(
        json.dumps(upstream, ensure_ascii=False),
        encoding="utf-8",
    )
    bundle = load_localization_bundle(
        catalog_kind="exercise",
        localization_path=EXERCISE_LOCALIZATION,
        taxonomy_path=EXERCISE_TAXONOMY,
    )
    profile = load_mapping_profile(EXERCISE_MAPPING)

    result = project_source(
        read_source(source_path),
        profile,
        localization_bundle=bundle,
    )

    source_by_id = {record["id"]: record for record in upstream}
    projected_by_id = {
        record.source_record_id: record for record in result.records
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
    assert set(projected_by_id) == set(source_by_id)

    taxonomy = bundle.taxonomy
    assert taxonomy is not None
    for source_id, source in source_by_id.items():
        entry = bundle.exercise_entries[source_id]
        projected = projected_by_id[source_id]
        assert projected.model_dump(mode="json") == {
            "source_name": profile.source_name,
            "source_record_id": source_id,
            "dataset_version": profile.dataset_version,
            "license": profile.license,
            "attribution": profile.attribution,
            "name": entry.name_zh_cn,
            "exercise_type": profile.projection.category_map[source["category"]],
            "primary_muscle": taxonomy.muscles[source["primaryMuscles"][0]],
            "secondary_muscles": [
                taxonomy.muscles[value] for value in source["secondaryMuscles"]
            ],
            "met": None,
            "aliases": [source["name"], *entry.aliases, *entry.pinyin],
            "provenance": {
                "profile": f"{profile.profile_name}@{profile.profile_version}",
                "upstream_name": source["name"],
                "original_category": source["category"],
                "equipment": source["equipment"],
                "level": source["level"],
                "mechanic": source["mechanic"],
                "force": source["force"],
                "instructions": source["instructions"],
                "image_count": len(source["images"]),
                "upstream": {
                    "name": source["name"],
                    "primary_muscle": source["primaryMuscles"][0],
                    "secondary_muscles": source["secondaryMuscles"],
                    "equipment": source["equipment"],
                    "level": source["level"],
                    "mechanic": source["mechanic"],
                    "force": source["force"],
                    "instructions": source["instructions"],
                },
                "localization": {
                    "locale": bundle.locale,
                    "asset_version": bundle.version,
                    "taxonomy_version": taxonomy.version,
                    "equipment": (
                        taxonomy.equipment[source["equipment"]]
                        if source["equipment"] is not None
                        else None
                    ),
                    "level": (
                        taxonomy.levels[source["level"]]
                        if source["level"] is not None
                        else None
                    ),
                    "mechanic": (
                        taxonomy.mechanics[source["mechanic"]]
                        if source["mechanic"] is not None
                        else None
                    ),
                    "force": (
                        taxonomy.forces[source["force"]]
                        if source["force"] is not None
                        else None
                    ),
                    "category": taxonomy.categories[source["category"]],
                    "instructions": list(entry.instructions_zh_cn),
                },
            },
        }


def test_bundled_tfda_snapshot_contains_only_complete_foods() -> None:
    payload = json.loads(FOOD_SNAPSHOT.read_text(encoding="utf-8"))

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
    rice = next(
        record
        for record in payload["foods"]
        if record["source_record_id"] == "A0550601"
    )
    assert rice["name"] == "米饭"
    assert {"白飯", "白饭", "米飯", "Cooked rice"} <= set(rice["aliases"])
    assert rice["provenance"]["profile"] == "tfda-foods@2.0.0"
    assert rice["provenance"]["localization"] == {
        "asset_version": "1.3.1",
        "locale": "zh-CN",
        "method": "record_override",
        "upstream_name": "白飯",
    }


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
                            record["provenance"]["localization"]["upstream_name"],
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
    by_id = {
        record["source_record_id"]: record for record in payload["exercises"]
    }
    full_squat = by_id["Barbell_Full_Squat"]
    standard_squat = by_id["Barbell_Squat"]
    assert full_squat["name"] == "杠铃深蹲"
    assert {"杠铃全蹲", "杠铃深蹲到底"} <= set(full_squat["aliases"])
    assert standard_squat["name"] == "杠铃标准深蹲"
    assert "标准杠铃深蹲" in standard_squat["aliases"]
    assert full_squat["primary_muscle"] == "股四头肌"
    assert full_squat["provenance"]["profile"] == "free-exercise-db@2.0.0"
    assert full_squat["provenance"]["localization"]["locale"] == "zh-CN"
    assert full_squat["provenance"]["localization"]["equipment"] == "杠铃"
    assert full_squat["provenance"]["localization"]["level"] == "中级"
    assert full_squat["provenance"]["localization"]["category"] == "力量训练"
    assert full_squat["provenance"]["localization"]["instructions"][0].startswith(
        "为确保安全"
    )
