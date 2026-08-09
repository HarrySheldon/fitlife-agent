from pathlib import Path
from unittest.mock import Mock

from backend.catalog_receiver.mapping import load_mapping_profile
from backend.catalog_receiver.service import CatalogReceiver


ROOT = Path(__file__).parent
PROFILE = Path(__file__).parents[2] / "data/catalog/mappings/tfda-foods.v1.json"


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
    bad.write_text(text.replace("粗脂肪,g,0.3", "膳食纖維,g,0.3"), encoding="utf-8")
    sink = Mock()

    result = CatalogReceiver(sink).import_catalog(bad, mapping=PROFILE)

    sink.import_records.assert_not_called()
    assert result.report.has_errors is True
    assert result.report.transaction == {"status": "blocked", "reason": "validation_errors"}
