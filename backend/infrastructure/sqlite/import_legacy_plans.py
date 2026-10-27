"""Copy a file-backed data directory into the SQLite plan store.

Run as a command, never from a request:

    python -m backend.infrastructure.sqlite.import_legacy_plans \
        --data-dir <path> --dry-run
    python -m backend.infrastructure.sqlite.import_legacy_plans \
        --data-dir <path> --apply

Three properties matter more than the copy itself.

**Dry run is read-only.** It opens no database, writes nothing, and moves
nothing. An inventory that could change state would be run against production
to "see what it would do", which is exactly the moment it must not.

**Files are never deleted.** The import copies. The files stay authoritative
until the deployment flips ``plan_storage_mode``, and they stay on disk after
that as the only remaining copy of the pre-migration state. Deleting them is a
separate, explicit decision.

**A file with no owner is refused, not assigned.** Every plan file lives at
``users/<owner>/plans/plan-<hex>.json``. A file anywhere else has no owner
binding, and inventing one would put somebody else's plan in somebody's history.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from backend.application.ports.plan_repository import StoredPlan, StoredPlanDraft, legacy_head

_USER_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_PLAN_FILE = re.compile(r"^plan-[a-f0-9]{8,64}\.json$")
_DRAFT_FILE = re.compile(r"^draft-[a-f0-9]{16,64}\.json$")


@dataclass
class OwnerInventory:
    user_id: str
    plans: list[StoredPlan] = field(default_factory=list)
    drafts: list[StoredPlanDraft] = field(default_factory=list)

    @property
    def head(self):
        return legacy_head(self.plans)


@dataclass
class Inventory:
    data_dir: Path
    owners: dict[str, OwnerInventory] = field(default_factory=dict)
    refused: list[tuple[str, str]] = field(default_factory=list)

    @property
    def plan_count(self) -> int:
        return sum(len(owner.plans) for owner in self.owners.values())

    @property
    def draft_count(self) -> int:
        return sum(len(owner.drafts) for owner in self.owners.values())

    def report(self) -> dict:
        return {
            "data_dir": str(self.data_dir),
            "owners": len(self.owners),
            "plans": self.plan_count,
            "drafts": self.draft_count,
            "refused": [{"path": path, "reason": reason} for path, reason in self.refused],
            "heads": {user_id: (owner.head.plan_id if owner.head else None)
                      for user_id, owner in sorted(self.owners.items())},
        }


def inventory(data_dir: Path) -> Inventory:
    """Everything the directory holds, or why a file could not be read."""
    data_dir = Path(data_dir)
    found = Inventory(data_dir=data_dir)
    users_root = data_dir / "users"
    if not users_root.is_dir():
        return found

    for entry in sorted(users_root.iterdir()):
        if entry.name.startswith("."):
            # Quarantined account directories: a deletion in progress, not data.
            continue
        if not entry.is_dir():
            _refuse_file(found, entry, "not an owner directory")
            continue
        if not _USER_ID.fullmatch(entry.name):
            _refuse_tree(found, entry, "directory name is not a user id")
            continue
        owner = found.owners.setdefault(entry.name, OwnerInventory(entry.name))
        _collect(found, owner, entry / "plans", _PLAN_FILE, StoredPlan, owner.plans)
        _collect(found, owner, entry / "plan-drafts", _DRAFT_FILE, StoredPlanDraft,
                 owner.drafts)
        # A plan file anywhere else in the owner's tree has no place it belongs:
        # the layout *is* the binding, so an unexpected location is a refusal.
        for stray in entry.rglob("plan-*.json"):
            if stray.parent != entry / "plans":
                _refuse_file(found, stray, "plan file outside users/<owner>/plans")
    return found


def _collect(found: Inventory, owner: OwnerInventory, directory: Path,
             pattern: re.Pattern[str], model, into: list) -> None:
    if not directory.is_dir():
        return
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        if not pattern.fullmatch(path.name):
            # Only a file that *looks* like history is a refusal. A stray README
            # or a leftover temp file is not data this import should refuse over.
            if path.name.startswith(("plan-", "draft-")):
                _refuse_file(found, path, "unrecognised file name")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            into.append(model.model_validate(payload))
        except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as error:
            _refuse_file(found, path, f"unreadable: {type(error).__name__}")


def _refuse_file(found: Inventory, path: Path, reason: str) -> None:
    found.refused.append((str(path), reason))


def _refuse_tree(found: Inventory, root: Path, reason: str) -> None:
    for path in sorted(root.rglob("*.json")):
        _refuse_file(found, path, reason)


def apply(data_dir: Path, database) -> dict:
    """Import everything, then record that the import completed.

    The completion record is written last and only if every owner succeeded: the
    factory reads it to decide whether ``sqlite`` may be authoritative, so a
    partial import must leave it absent and keep the deployment on files.

    The allergy list is copied too. It is the last hard constraint whose only
    authority is a file, and a confirmation cannot approve a candidate reviewed
    against a value it cannot name the version of -- so the same authorized,
    explicit migration that moves the plans moves the restrictions with them.
    """
    from backend.infrastructure.repositories.sqlite_plan_repository import (
        SQLitePlanRepository,
    )
    from backend.infrastructure.repositories.sqlite_profile_target_repository import (
        SQLiteProfileTargetRepository,
    )
    from backend.tools.profile_loader import load_profile

    found = inventory(data_dir)
    if found.refused:
        raise SystemExit(_refusals(found))

    repository = SQLitePlanRepository(database)
    profiles = SQLiteProfileTargetRepository(database)
    imported = {"owners": 0, "plans": 0, "drafts": 0, "safety": 0}
    for user_id, owner in sorted(found.owners.items()):
        counts = repository.import_history(user_id, owner.plans, owner.drafts,
                                           head=owner.head)
        imported["owners"] += 1
        imported["plans"] += counts["plans"]
        imported["drafts"] += counts["drafts"]
        imported["safety"] += _import_safety(profiles, load_profile,
                                             data_dir, user_id)

    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO plan_import_state (
                id, data_dir, completed_at, owner_count, plan_count, draft_count
            ) VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                data_dir=excluded.data_dir, completed_at=excluded.completed_at,
                owner_count=excluded.owner_count, plan_count=excluded.plan_count,
                draft_count=excluded.draft_count
            """,
            (str(Path(data_dir).resolve()), _now(), imported["owners"],
             found.plan_count, found.draft_count),
        )
    return imported


def _import_safety(profiles, load_profile, data_dir: Path, user_id: str) -> int:
    """One versioned allergy list per owner, or zero when it already matches.

    A missing profile file is not an error: the account has plans but no profile,
    which means its restrictions are unknown rather than empty. Writing an empty
    list would be inventing "verified to have no allergies", so nothing is written
    and a later confirmation refuses until the profile is saved.
    """
    from backend.application.ports.profile_target_repository import SafetyVersionInput

    path = Path(data_dir) / "users" / user_id / "user_profile.json"
    if not path.is_file():
        return 0
    try:
        profile = load_profile(path)
    except (OSError, UnicodeError, ValueError):
        raise SystemExit(
            f"refusing to import: {path} is not a readable profile") from None
    before = profiles.get_latest_safety(user_id)
    after = profiles.append_safety_if_changed(
        user_id,
        SafetyVersionInput(
            allergies_or_restrictions=tuple(profile.allergies_or_restrictions)),
    )
    return 0 if before is not None and before.id == after.id else 1


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _refusals(found: Inventory) -> str:
    lines = [f"refusing to import {len(found.refused)} file(s) with no valid owner binding:"]
    lines += [f"  {path}: {reason}" for path, reason in found.refused[:20]]
    if len(found.refused) > 20:
        lines.append(f"  ... and {len(found.refused) - 20} more")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="import_legacy_plans")
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--database", type=Path, default=None)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    found = inventory(args.data_dir)
    if args.dry_run:
        print(json.dumps(found.report(), ensure_ascii=False, indent=2))
        return 0 if not found.refused else 1

    if found.refused:
        print(_refusals(found), file=sys.stderr)
        return 1

    from backend.infrastructure.sqlite.database import SQLiteDatabase
    from backend.infrastructure.sqlite.migrations import run_migrations
    from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS

    database = SQLiteDatabase(args.database or Path(args.data_dir) / "fitlife.sqlite3")
    run_migrations(database, RECORDS_MIGRATIONS)
    imported = apply(args.data_dir, database)
    print(json.dumps({"imported": imported, "inventory": found.report()},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
