from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.infrastructure.sqlite.backup import backup_database
from backend.infrastructure.sqlite.runtime import get_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a verified FitLife SQLite backup")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or (
        Path("backups")
        / f"fitlife-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.sqlite3"
    )
    result = backup_database(get_database(), output)
    print(
        json.dumps(
            {
                "path": str(result.path),
                "sha256": result.checksum,
                "bytes": result.bytes,
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
