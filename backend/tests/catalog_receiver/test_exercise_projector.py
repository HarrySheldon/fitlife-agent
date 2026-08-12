import json
from pathlib import Path

import pytest

from backend.catalog_receiver.localization import load_localization_bundle
from backend.catalog_receiver.mapping import load_mapping_profile
from backend.catalog_receiver.models import ReceiverError
from backend.catalog_receiver.projectors import project_source
from backend.catalog_receiver.readers import read_source


ROOT = Path(__file__).parent
PROFILE = Path(__file__).parents[2] / "data" / "catalog" / "mappings" / "free-exercise-db.v1.json"
LOCALIZATION = ROOT / "fixtures" / "exercise-localization.zh-CN.json"
TAXONOMY = Path(__file__).parents[2] / "data" / "catalog" / "localizations" / "exercise-taxonomy.zh-CN.v1.json"


def test_applies_complete_exercise_and_taxonomy_localization(tmp_path: Path) -> None:
    source = tmp_path / "squat.json"
    fixture = json.loads((ROOT / "fixtures" / "free-exercises.json").read_text(encoding="utf-8"))
    source.write_text(json.dumps([fixture[0]]), encoding="utf-8")
    bundle = load_localization_bundle(
        catalog_kind="exercise",
        localization_path=LOCALIZATION,
        taxonomy_path=TAXONOMY,
    )

    result = project_source(
        read_source(source),
        load_mapping_profile(PROFILE),
        localization_bundle=bundle,
    )

    assert result.issues == ()
    assert result.enrichment_count == 1
    assert result.enrichment_coverage == 1
    squat = result.records[0]
    assert squat.name == "杠铃深蹲"
    assert squat.aliases == ("Barbell Full Squat", "深蹲", "gangling shendun")
    assert squat.primary_muscle == "股四头肌"
    assert squat.secondary_muscles == ("小腿肌群", "臀肌")
    assert squat.provenance["upstream"] == {
        "name": "Barbell Full Squat",
        "primary_muscle": "quadriceps",
        "secondary_muscles": ["calves", "glutes"],
        "equipment": "barbell",
        "level": "intermediate",
        "mechanic": "compound",
        "force": "push",
        "instructions": ["Stand with the bar.", "Squat."],
    }
    assert squat.provenance["localization"] == {
        "locale": "zh-CN",
        "asset_version": "2.0.0",
        "taxonomy_version": "1.0.0",
        "equipment": "杠铃",
        "level": "中级",
        "mechanic": "复合动作",
        "force": "推",
        "category": "力量训练",
        "instructions": ["将杠铃置于上背部。", "屈髋屈膝下蹲。"],
    }
    assert {
        key: squat.provenance[key]
        for key in (
            "profile",
            "upstream_name",
            "original_category",
            "equipment",
            "level",
            "mechanic",
            "force",
            "instructions",
            "image_count",
        )
    } == {
        "profile": "free-exercise-db@2.0.0",
        "upstream_name": "Barbell Full Squat",
        "original_category": "strength",
        "equipment": "barbell",
        "level": "intermediate",
        "mechanic": "compound",
        "force": "push",
        "instructions": ["Stand with the bar.", "Squat."],
        "image_count": 1,
    }


def test_configured_exercise_localization_rejects_unlisted_compatible_exercise() -> None:
    bundle = load_localization_bundle(
        catalog_kind="exercise",
        localization_path=LOCALIZATION,
        taxonomy_path=TAXONOMY,
    )

    result = project_source(
        read_source(ROOT / "fixtures" / "free-exercises.json"),
        load_mapping_profile(PROFILE),
        localization_bundle=bundle,
    )

    assert [record.source_record_id for record in result.records] == ["Barbell_Full_Squat"]
    assert result.rejected_count == 1
    assert result.enrichment_count == 1
    assert result.enrichment_coverage == 0.5
    issue = next(issue for issue in result.issues if issue.code == "LOCALIZATION_MISSING")
    assert issue.severity == "error"
    assert issue.record == "Run"
    assert issue.field == "source_record_id"
    assert all(record.name != "Run" for record in result.records)
    coverage_issue = next(
        issue
        for issue in result.issues
        if issue.code == "LOCALIZATION_COVERAGE_INSUFFICIENT"
    )
    assert coverage_issue.observed == 0.5
    assert coverage_issue.expected == "1.0"


def test_v2_profile_without_bundle_reports_blocking_localization_coverage() -> None:
    result = project_source(
        read_source(ROOT / "fixtures" / "free-exercises.json"),
        load_mapping_profile(PROFILE),
    )

    issue = next(
        issue
        for issue in result.issues
        if issue.code == "LOCALIZATION_COVERAGE_INSUFFICIENT"
    )
    assert issue.severity == "error"
    assert issue.observed == 0
    assert issue.expected == "1.0"
    assert result.enrichment_coverage == issue.observed
    assert any(record.name == "Run" for record in result.records)


def test_minimum_zero_profile_preserves_legacy_english_fallback() -> None:
    profile = load_mapping_profile(PROFILE)
    assert profile.enrichment is not None
    legacy_profile = profile.model_copy(
        update={
            "enrichment": profile.enrichment.model_copy(
                update={"minimum_coverage": 0}
            )
        }
    )

    result = project_source(
        read_source(ROOT / "fixtures" / "free-exercises.json"),
        legacy_profile,
        enrichment_path=ROOT / "fixtures" / "free-exercises.zh-CN.json",
    )

    assert not any(
        issue.code == "LOCALIZATION_COVERAGE_INSUFFICIENT"
        for issue in result.issues
    )
    assert any(record.name == "Run" for record in result.records)
    assert any(issue.code == "ENRICHMENT_ENGLISH_FALLBACK" for issue in result.issues)
    assert result.enrichment_coverage == 0.5


def test_localized_exercise_aliases_use_nfkc_casefold_dedupe(tmp_path: Path) -> None:
    payload = json.loads(LOCALIZATION.read_text(encoding="utf-8"))
    payload["entries"]["Barbell_Full_Squat"]["aliases"] = [
        "Ｂａｒｂｅｌｌ Ｆｕｌｌ Ｓｑｕａｔ",
        "深蹲",
    ]
    localized_path = tmp_path / "exercise-localization.json"
    localized_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    source = tmp_path / "squat.json"
    exercises = json.loads(
        (ROOT / "fixtures" / "free-exercises.json").read_text(encoding="utf-8")
    )
    source.write_text(json.dumps([exercises[0]]), encoding="utf-8")
    bundle = load_localization_bundle(
        catalog_kind="exercise",
        localization_path=localized_path,
        taxonomy_path=TAXONOMY,
    )

    result = project_source(
        read_source(source),
        load_mapping_profile(PROFILE),
        localization_bundle=bundle,
    )

    assert result.records[0].aliases == (
        "Barbell Full Squat",
        "深蹲",
        "gangling shendun",
    )
    assert "杠铃深蹲" not in result.records[0].aliases


def test_reports_all_unknown_taxonomy_values_with_precise_fields(tmp_path: Path) -> None:
    exercise = {
        "id": "Barbell_Full_Squat",
        "name": "Barbell Full Squat",
        "force": "unknown-force",
        "level": "unknown-level",
        "mechanic": "unknown-mechanic",
        "equipment": "unknown-equipment",
        "primaryMuscles": ["unknown-primary"],
        "secondaryMuscles": [
            "unknown-secondary-b",
            "unknown-secondary-b",
            "unknown-secondary-a",
        ],
        "instructions": ["Stand with the bar.", "Squat."],
        "category": "unknown-category",
        "images": [],
    }
    profile = load_mapping_profile(PROFILE)
    category_map = dict(profile.projection.category_map)
    category_map["unknown-category"] = "strength"
    profile = profile.model_copy(
        update={
            "projection": profile.projection.model_copy(
                update={"category_map": category_map}
            )
        }
    )
    source = tmp_path / "unknown-taxonomy.json"
    source.write_text(json.dumps([exercise]), encoding="utf-8")
    bundle = load_localization_bundle(
        catalog_kind="exercise",
        localization_path=LOCALIZATION,
        taxonomy_path=TAXONOMY,
    )

    result = project_source(
        read_source(source),
        profile,
        localization_bundle=bundle,
    )

    assert result.records == ()
    missing = [
        issue
        for issue in result.issues
        if issue.code == "LOCALIZATION_MISSING"
    ]
    assert [(issue.field, issue.observed) for issue in missing] == [
        ("taxonomy.muscles.primary", "unknown-primary"),
        ("taxonomy.muscles.secondary[0]", "unknown-secondary-b"),
        ("taxonomy.muscles.secondary[2]", "unknown-secondary-a"),
        ("taxonomy.equipment", "unknown-equipment"),
        ("taxonomy.level", "unknown-level"),
        ("taxonomy.mechanic", "unknown-mechanic"),
        ("taxonomy.force", "unknown-force"),
        ("taxonomy.category", "unknown-category"),
    ]


@pytest.mark.parametrize(
    ("bundle_update", "field"),
    [
        ({"catalog_kind": "food"}, "catalog_kind"),
        ({"source_name": "another-exercise-source"}, "source_name"),
    ],
)
def test_rejects_exercise_localization_bundle_that_does_not_match_profile(
    bundle_update: dict[str, str],
    field: str,
) -> None:
    bundle = load_localization_bundle(
        catalog_kind="exercise",
        localization_path=LOCALIZATION,
        taxonomy_path=TAXONOMY,
    ).model_copy(update=bundle_update)

    with pytest.raises(ReceiverError) as raised:
        project_source(
            read_source(ROOT / "fixtures" / "free-exercises.json"),
            load_mapping_profile(PROFILE),
            localization_bundle=bundle,
        )

    assert raised.value.code == "LOCALIZATION_INVALID"
    assert raised.value.issue is not None
    assert raised.value.issue.field == field


def test_maps_categories_excludes_stretching_and_merges_enrichment() -> None:
    result = project_source(
        read_source(ROOT / "fixtures" / "free-exercises.json"),
        load_mapping_profile(PROFILE),
        enrichment_path=ROOT / "fixtures" / "free-exercises.zh-CN.json",
    )

    assert result.scanned_count == 3
    assert result.excluded_count == 1
    assert len(result.records) == 2
    assert result.enrichment_count == 1
    assert result.enrichment_coverage == 0
    coverage_issue = next(
        issue
        for issue in result.issues
        if issue.code == "LOCALIZATION_COVERAGE_INSUFFICIENT"
    )
    assert result.enrichment_coverage == coverage_issue.observed
    squat, run = result.records
    assert squat.name == "杠铃深蹲"
    assert squat.aliases == ("Barbell Full Squat", "深蹲", "gangling shendun")
    assert squat.exercise_type == "strength"
    assert squat.provenance["equipment"] == "barbell"
    assert "images" not in squat.provenance
    assert squat.provenance["image_count"] == 1
    assert run.name == "Run"
    assert run.exercise_type == "cardio"
    assert any(issue.code == "ENRICHMENT_ENGLISH_FALLBACK" for issue in result.issues)
    assert any(issue.code == "EXERCISE_CATEGORY_EXCLUDED" for issue in result.issues)


def test_reports_orphan_enrichment_as_warning(tmp_path: Path) -> None:
    enrichment = tmp_path / "aliases.json"
    enrichment.write_text(
        '{"Missing":{"name_zh":"缺失","aliases":[],"pinyin":["queshi"]}}',
        encoding="utf-8",
    )

    result = project_source(
        read_source(ROOT / "fixtures" / "free-exercises.json"),
        load_mapping_profile(PROFILE),
        enrichment_path=enrichment,
    )

    orphan = next(issue for issue in result.issues if issue.code == "ENRICHMENT_ORPHAN")
    assert orphan.severity == "warning"


@pytest.mark.parametrize(
    "payload",
    [
        '{"A":{"name_zh":"深蹲","aliases":[],"pinyin":[]},"A":{"name_zh":"卧推","aliases":[],"pinyin":[]}}',
        '{"A":{"name_zh":"深蹲","aliases":[],"pinyin":["深蹲"]}}',
    ],
)
def test_rejects_invalid_enrichment(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "bad.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(ReceiverError) as raised:
        project_source(
            read_source(ROOT / "fixtures" / "free-exercises.json"),
            load_mapping_profile(PROFILE),
            enrichment_path=path,
        )

    assert raised.value.code == "ENRICHMENT_INVALID"
