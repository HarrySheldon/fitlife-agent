import json
from pathlib import Path


CATALOG_ROOT = Path(__file__).parents[2] / "data" / "catalog"


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
