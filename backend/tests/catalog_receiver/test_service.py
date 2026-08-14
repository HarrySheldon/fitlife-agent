from pathlib import Path
from unittest.mock import Mock

from backend.catalog_receiver import localization as localization_module
from backend.catalog_receiver import service as service_module
from backend.catalog_receiver.localization import load_localization_bundle
from backend.catalog_receiver.mapping import load_mapping_profile
from backend.catalog_receiver.projectors import project_source
from backend.catalog_receiver.service import CatalogReceiver


ROOT = Path(__file__).parent
PROFILE = Path(__file__).parents[2] / "data/catalog/mappings/tfda-foods.v1.json"
EXERCISE_PROFILE = Path(__file__).parents[2] / "data/catalog/mappings/free-exercise-db.v1.json"
EXERCISE_LOCALIZATION = ROOT / "fixtures/exercise-localization.zh-CN.json"
FOOD_LOCALIZATION = ROOT / "fixtures/food-localization.zh-CN.json"
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
        enrichment_path=ROOT / "fixtures/free-exercises.zh-CN.json",
    )

    sink.import_records.assert_not_called()
    assert result.report.enrichment_count == 1
    assert result.report.issue_counts["LOCALIZATION_COVERAGE_INSUFFICIENT"] == 1
    coverage_issue = next(
        issue
        for issue in result.report.issues
        if issue.code == "LOCALIZATION_COVERAGE_INSUFFICIENT"
    )
    assert result.report.enrichment_coverage == coverage_issue.observed
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


def test_localization_candidates_load_once_and_selected_bundle_reaches_projector(
    monkeypatch,
) -> None:
    real_load_document = localization_module._load_asset_document
    real_resolve_bundle = service_module.resolve_localization_bundle
    real_project_source = project_source
    load_counts: dict[Path, int] = {}
    resolved_bundles = []
    projected_bundles = []

    def counted_load(path, *, label):
        resolved = Path(path).resolve()
        if label == "Localization":
            load_counts[resolved] = load_counts.get(resolved, 0) + 1
        return real_load_document(path, label=label)

    def capture_resolved_bundle(**kwargs):
        bundle = real_resolve_bundle(**kwargs)
        resolved_bundles.append(bundle)
        return bundle

    def capture_bundle(
        source,
        profile,
        *,
        enrichment_path=None,
        localization_bundle=None,
    ):
        projected_bundles.append(localization_bundle)
        return real_project_source(
            source,
            profile,
            enrichment_path=enrichment_path,
            localization_bundle=localization_bundle,
        )

    monkeypatch.setattr(localization_module, "_load_asset_document", counted_load)
    monkeypatch.setattr(
        service_module,
        "resolve_localization_bundle",
        capture_resolved_bundle,
    )
    monkeypatch.setattr(service_module, "project_source", capture_bundle)

    CatalogReceiver().validate(
        ROOT / "fixtures/tfda-foods.csv",
        mapping=PROFILE,
        localization_paths=(EXERCISE_LOCALIZATION, FOOD_LOCALIZATION),
    )

    assert load_counts == {
        EXERCISE_LOCALIZATION.resolve(): 1,
        FOOD_LOCALIZATION.resolve(): 1,
    }
    assert len(resolved_bundles) == 1
    assert projected_bundles == resolved_bundles
    assert resolved_bundles[0].localization_path == FOOD_LOCALIZATION.resolve()
