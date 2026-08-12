from pathlib import Path
from unittest.mock import Mock

from backend.catalog_receiver import service as service_module
from backend.catalog_receiver.localization import load_localization_bundle
from backend.catalog_receiver.mapping import load_mapping_profile
from backend.catalog_receiver.projectors import project_source
from backend.catalog_receiver.service import CatalogReceiver


ROOT = Path(__file__).parent
PROFILE = Path(__file__).parents[2] / "data/catalog/mappings/tfda-foods.v1.json"
EXERCISE_PROFILE = Path(__file__).parents[2] / "data/catalog/mappings/free-exercise-db.v1.json"
EXERCISE_LOCALIZATION = ROOT / "fixtures/exercise-localization.zh-CN.json"
EXERCISE_TAXONOMY = Path(__file__).parents[2] / "data/catalog/localizations/exercise-taxonomy.zh-CN.v1.json"


def test_validate_is_read_only_and_can_write_audit_files(tmp_path: Path) -> None:
    sink = Mock()
    result = CatalogReceiver(sink).validate(
        ROOT / "fixtures/tfda-foods.csv",
        mapping=PROFILE,
        output_dir=tmp_path,
    )

    assert result.report.accepted_count == 1
    assert result.report.has_errors is False
    sink.import_records.assert_not_called()
    assert (tmp_path / "normalized-foods.json").exists()


def test_import_calls_sink_only_after_successful_validation(tmp_path: Path) -> None:
    sink = Mock()
    sink.import_records.return_value = {"status": "committed", "inserted_count": 1}

    result = CatalogReceiver(sink).import_catalog(
        ROOT / "fixtures/tfda-foods.csv",
        mapping=load_mapping_profile(PROFILE),
    )

    sink.import_records.assert_called_once()
    assert result.report.transaction["status"] == "committed"


def test_import_blocks_sink_when_projection_has_errors(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    text = (ROOT / "fixtures/tfda-foods.csv").read_text(encoding="utf-8")
    bad.write_text(text.replace("總碳水化合物,g,28.2", "總碳水化合物,mg,unknown"), encoding="utf-8")
    sink = Mock()

    result = CatalogReceiver(sink).import_catalog(bad, mapping=PROFILE)

    sink.import_records.assert_not_called()
    assert result.report.has_errors is True
    assert result.report.transaction == {"status": "blocked", "reason": "validation_errors"}


def test_import_blocks_sink_when_v2_exercise_coverage_is_insufficient() -> None:
    sink = Mock()

    result = CatalogReceiver(sink).import_catalog(
        ROOT / "fixtures/free-exercises.json",
        mapping=EXERCISE_PROFILE,
    )

    sink.import_records.assert_not_called()
    assert result.report.issue_counts["LOCALIZATION_COVERAGE_INSUFFICIENT"] == 1
    assert result.report.transaction == {"status": "blocked", "reason": "validation_errors"}


def test_import_blocks_sink_when_injected_projection_has_errors(monkeypatch) -> None:
    sink = Mock()
    profile = load_mapping_profile(EXERCISE_PROFILE)
    bundle = load_localization_bundle(
        catalog_kind="exercise",
        localization_path=EXERCISE_LOCALIZATION,
        taxonomy_path=EXERCISE_TAXONOMY,
    )
    real_project_source = project_source

    def project_with_localization(source, configured_profile, *, enrichment_path=None):
        return real_project_source(
            source,
            configured_profile,
            enrichment_path=enrichment_path,
            localization_bundle=bundle,
        )

    monkeypatch.setattr(service_module, "project_source", project_with_localization)

    result = CatalogReceiver(sink).import_catalog(
        ROOT / "fixtures/free-exercises.json",
        mapping=profile,
    )

    sink.import_records.assert_not_called()
    assert result.report.has_errors is True
    assert result.report.issue_counts["LOCALIZATION_MISSING"] == 1
    assert result.report.transaction == {"status": "blocked", "reason": "validation_errors"}
    assert [record.source_record_id for record in result.records] == ["Barbell_Full_Squat"]
