from pathlib import Path

from backend.catalog_receiver.models import ReceiverIssue
from backend.catalog_receiver.reporting import MAX_ISSUE_DETAILS, build_report, write_run_artifacts
from backend.catalog_receiver.mapping import load_mapping_profile
from backend.catalog_receiver.projectors import project_source
from backend.catalog_receiver.readers import read_source


ROOT = Path(__file__).parent


def test_report_caps_details_and_includes_schema_for_errors() -> None:
    profile = load_mapping_profile(Path(__file__).parents[2] / "data/catalog/mappings/tfda-foods.v1.json")
    source = read_source(ROOT / "fixtures/tfda-foods.csv")
    projection = project_source(source, profile)
    issues = tuple(
        ReceiverIssue(severity="error", code="CANONICAL_RECORD_INVALID", record=index)
        for index in range(MAX_ISSUE_DETAILS + 5)
    )

    report = build_report(source=source.metadata, profile=profile, projection=projection, validation_issues=issues)

    assert report.total_issue_count == MAX_ISSUE_DETAILS + 5
    assert len(report.issues) == MAX_ISSUE_DETAILS
    assert report.issues_truncated is True
    assert report.canonical_schema is not None
    assert report.canonical_example["basis_type"] == "per_100g"
    assert report.issues[0].message
    assert report.issues[0].suggestion


def test_writes_reports_and_only_successful_normalized_snapshot(tmp_path: Path) -> None:
    profile = load_mapping_profile(Path(__file__).parents[2] / "data/catalog/mappings/tfda-foods.v1.json")
    source = read_source(ROOT / "fixtures/tfda-foods.csv")
    projection = project_source(source, profile)
    report = build_report(source=source.metadata, profile=profile, projection=projection)

    write_run_artifacts(tmp_path, report, projection.records)

    assert (tmp_path / "catalog-import-report.json").exists()
    assert "Accepted: 1" in (tmp_path / "catalog-import-report.txt").read_text(encoding="utf-8")
    assert (tmp_path / "normalized-foods.json").exists()
    assert str(ROOT.resolve()) not in (tmp_path / "catalog-import-report.json").read_text(encoding="utf-8")
