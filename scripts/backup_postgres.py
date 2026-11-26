from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import get_settings
from backend.infrastructure.postgres.backup import (
    ENCRYPTION_KEY_NOTICE,
    backup_postgres_database,
    verify_backup_file,
    verify_postgres_database,
)
from backend.infrastructure.postgres.database import PostgresDatabase


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or verify a FitLife PostgreSQL backup")
    parser.add_argument("--database-url", type=str, default=None)
    parser.add_argument("--schema", type=str, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--manifest",
        action="store_true",
        help="Write a companion <output>.manifest.json file next to the backup.",
    )
    parser.add_argument(
        "--verify-only",
        nargs="?",
        const="__LIVE__",
        default=None,
        help="Verify the live PostgreSQL DB (no arg) or an existing backup file (with path).",
    )
    args = parser.parse_args()

    settings = get_settings()
    database = PostgresDatabase(
        args.database_url or settings.database_url,
        schema=args.schema or settings.database_schema,
    )

    if args.verify_only == "__LIVE__":
        result = verify_postgres_database(database)
    elif args.verify_only is not None:
        result = verify_backup_file(Path(args.verify_only))
    else:
        output = args.output or (
            Path("backups")
            / f"fitlife-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.pg.json"
        )
        result = backup_postgres_database(database, output)

    summary = {
        "path": str(result.path) if result.path is not None else None,
        "sha256": result.checksum,
        "bytes": result.bytes,
        "integrity_check": result.integrity_check,
        "schema_version": result.schema_version,
        "user_count": result.user_count,
        "model_connection_count": result.model_connection_count,
        "agent_run_count": result.agent_run_count,
        "rag_active_release": result.rag_active_release,
        "backup_format": result.backup_format,
        "encryption_key_notice": ENCRYPTION_KEY_NOTICE,
    }

    if args.manifest and result.path is not None:
        manifest_path = Path(f"{result.path}.manifest.json")
        manifest_payload = {
            **summary,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        manifest_path.write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        summary["manifest_path"] = str(manifest_path)

    print(json.dumps(summary, separators=(",", ":")))


if __name__ == "__main__":
    main()
