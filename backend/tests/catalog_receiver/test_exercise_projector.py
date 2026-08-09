from pathlib import Path

import pytest

from backend.catalog_receiver.mapping import load_mapping_profile
from backend.catalog_receiver.models import ReceiverError
from backend.catalog_receiver.projectors import project_source
from backend.catalog_receiver.readers import read_source


ROOT = Path(__file__).parent
PROFILE = Path(__file__).parents[2] / "data" / "catalog" / "mappings" / "free-exercise-db.v1.json"


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
    assert result.enrichment_coverage == 0.5
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
