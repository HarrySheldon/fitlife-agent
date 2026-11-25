from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.infrastructure.sqlite.backup import backup_database, verify_database_backup
from backend.infrastructure.sqlite.runtime import get_database


_ENCRYPTION_KEY_NOTICE = (
    "Model API keys stored in model_connections remain Fernet-encrypted. "
    "Back up SETTINGS_ENCRYPTION_KEY separately in a safe offline location."
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or verify a FitLife SQLite backup")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--manifest",
        action="store_true",
        help="Write a companion <output>.manifest.json file next to the backup.",
    )
    parser.add_argument(
        "--verify-only",
        type=Path,
        help="Verify an existing SQLite backup file without creating a new copy.",
    )
    args = parser.parse_args()

    if args.verify_only is not None:
        result = verify_database_backup(args.verify_only)
    else:
        output = args.output or (
            Path("backups")
            / f"fitlife-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.sqlite3"
        )
        result = backup_database(get_database(), output)

    summary = {
        "path": str(result.path),
        "sha256": result.checksum,
        "bytes": result.bytes,
        "integrity_check": result.integrity_check,
        "schema_version": result.schema_version,
        "user_count": result.user_count,
        "model_connection_count": result.model_connection_count,
        "encryption_key_notice": _ENCRYPTION_KEY_NOTICE,
    }

    if args.manifest:
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
