from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.catalog_receiver.models import ReceiverError
from backend.catalog_receiver.service import CatalogReceiver
from backend.catalog_receiver.sinks import SQLiteCatalogSink
from backend.config import get_settings
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


MAPPING_ROOT = PROJECT_ROOT / "backend" / "data" / "catalog" / "mappings"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and import the approved initial food and exercise catalogs."
    )
    parser.add_argument("--foods", type=Path, required=True)
    parser.add_argument("--exercises", type=Path, required=True)
    parser.add_argument("--exercise-aliases", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / ".tmp" / "catalog-import")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    food_mapping = MAPPING_ROOT / "tfda-foods.v1.json"
    exercise_mapping = MAPPING_ROOT / "free-exercise-db.v1.json"
    try:
        validator = CatalogReceiver()
        food_validation = validator.validate(
            args.foods,
            mapping=food_mapping,
            output_dir=args.output_dir / "foods",
        )
        exercise_validation = validator.validate(
            args.exercises,
            mapping=exercise_mapping,
            enrichment_path=args.exercise_aliases,
            output_dir=args.output_dir / "exercises",
        )
        validation_summary = {
            "foods": food_validation.report.model_dump(mode="json"),
            "exercises": exercise_validation.report.model_dump(mode="json"),
        }
        if food_validation.report.has_errors or exercise_validation.report.has_errors:
            print(json.dumps(validation_summary, ensure_ascii=False, indent=2, sort_keys=True))
            return 4

        database_path = args.database or get_settings().database_path
        database = SQLiteDatabase(database_path)
        run_migrations(database, RECORDS_MIGRATIONS)
        importer = CatalogReceiver(SQLiteCatalogSink(database))
        food_import = importer.import_catalog(
            args.foods,
            mapping=food_mapping,
            output_dir=args.output_dir / "foods",
        )
        exercise_import = importer.import_catalog(
            args.exercises,
            mapping=exercise_mapping,
            enrichment_path=args.exercise_aliases,
            output_dir=args.output_dir / "exercises",
        )
        print(
            json.dumps(
                {
                    "database": str(database_path),
                    "foods": food_import.report.transaction,
                    "exercises": exercise_import.report.transaction,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except ReceiverError as error:
        print(
            json.dumps(
                {"success": False, "error": {"code": error.code, "message": error.message}},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
