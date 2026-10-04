from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from backend.catalog_receiver.localization import LOCALIZATION_MISSING
from backend.catalog_receiver.models import ReceiverError
from backend.catalog_receiver.service import CatalogReceiver
from backend.catalog_receiver.sinks import SQLiteCatalogSink
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.tools.catalog_receiver",
        description="Inspect, validate, or import a local CSV/JSON catalog file.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect source structure without writes.")
    _source_arguments(inspect_parser)
    inspect_parser.add_argument("--catalog-kind", choices=("food", "exercise"), default="food")

    for command in ("validate", "import"):
        command_parser = subparsers.add_parser(command, help=f"{command.title()} a mapped catalog source.")
        _source_arguments(command_parser)
        command_parser.add_argument("--mapping", type=Path, required=True)
        command_parser.add_argument("--enrichment", type=Path)
        command_parser.add_argument(
            "--localization",
            dest="localizations",
            action="append",
            type=Path,
            default=[],
        )
        command_parser.add_argument("--taxonomy", type=Path)
        command_parser.add_argument("--output-dir", type=Path)
        if command == "import":
            command_parser.add_argument("--database", type=Path, required=True)
    return parser


def _source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", type=Path)
    parser.add_argument("--json-size-limit", type=int, default=100_000_000)
    parser.add_argument("--csv-delimiter")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "inspect":
            inspection = CatalogReceiver().inspect(
                args.source,
                catalog_kind=args.catalog_kind,
                json_size_limit=args.json_size_limit,
                csv_delimiter=args.csv_delimiter,
            )
            _print_json(inspection.model_dump(mode="json"))
            return 0

        if not args.localizations:
            raise ReceiverError(
                LOCALIZATION_MISSING,
                "At least one localization asset is required.",
                exit_code=4,
            )

        receiver = CatalogReceiver()
        if args.command == "import":
            preflight = receiver.validate(
                args.source,
                mapping=args.mapping,
                enrichment_path=args.enrichment,
                localization_paths=args.localizations,
                taxonomy_path=args.taxonomy,
                output_dir=args.output_dir,
                json_size_limit=args.json_size_limit,
                csv_delimiter=args.csv_delimiter,
            )
            if preflight.report.has_errors:
                _print_json(preflight.report.model_dump(mode="json"))
                return 4
            database = SQLiteDatabase(args.database)
            run_migrations(database, RECORDS_MIGRATIONS)
            receiver = CatalogReceiver(SQLiteCatalogSink(database))
            result = receiver.import_catalog(
                args.source,
                mapping=args.mapping,
                enrichment_path=args.enrichment,
                localization_paths=args.localizations,
                taxonomy_path=args.taxonomy,
                output_dir=args.output_dir,
                json_size_limit=args.json_size_limit,
                csv_delimiter=args.csv_delimiter,
            )
        else:
            result = receiver.validate(
                args.source,
                mapping=args.mapping,
                enrichment_path=args.enrichment,
                localization_paths=args.localizations,
                taxonomy_path=args.taxonomy,
                output_dir=args.output_dir,
                json_size_limit=args.json_size_limit,
                csv_delimiter=args.csv_delimiter,
            )
        _print_json(result.report.model_dump(mode="json"))
        return 4 if result.report.has_errors else 0
    except ReceiverError as error:
        _print_json(
            {
                "success": False,
                "error": {"code": error.code, "message": error.message},
            },
            stream=sys.stderr,
        )
        return error.exit_code


def _print_json(value: object, *, stream=None) -> None:
    print(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        file=stream or sys.stdout,
    )


if __name__ == "__main__":
    raise SystemExit(main())
