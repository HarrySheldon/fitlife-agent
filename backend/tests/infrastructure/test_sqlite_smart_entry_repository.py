from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from backend.application.ports.smart_entry_repository import (
    SmartEntryDraftPayload,
    SmartEntryRepositoryError,
)
from backend.domain.smart_entry import ResolvedCandidate
from backend.infrastructure.repositories.sqlite_smart_entry_repository import (
    SQLiteSmartEntryRepository,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.sqlite.migrations import run_migrations
from backend.infrastructure.sqlite.schema import RECORDS_MIGRATIONS


def _database() -> tuple[SQLiteDatabase, Path]:
    path = Path("backend/data") / f"test-smart-entry-{uuid4().hex}.sqlite3"
    database = SQLiteDatabase(path)
    run_migrations(database, RECORDS_MIGRATIONS)
    return database, path


def _payload(
    *,
    log_date: str = "2026-07-26",
    raw_text: str = "早餐：燕麦 50g",
) -> SmartEntryDraftPayload:
    candidate = ResolvedCandidate(
        id="segment-1",
        kind="food",
        raw_text="燕麦 50g",
        normalized_text="燕麦 50g",
        subject_text="燕麦",
        meal_context="breakfast",
        selected=True,
        selected_catalog_id="food-oats",
        catalog_choices=(),
        issues=(),
        values={
            "name": "燕麦",
            "amount": 50,
            "unit": "g",
            "calories": 190,
            "carbs": 34,
            "protein": 6.5,
            "fat": 3.5,
        },
        provenance={"source": "public"},
    )
    return SmartEntryDraftPayload(
        log_date=log_date,
        raw_text=raw_text,
        parser_version="smart-entry-parser-v1",
        candidates=(candidate,),
    )


def _cleanup(path: Path) -> None:
    for suffix in ("", "-shm", "-wal"):
        target = Path(f"{path}{suffix}")
        if target.exists():
            target.unlink()


def test_smart_entry_drafts_are_owner_scoped_versioned_and_date_searchable():
    database, path = _database()
    now = datetime(2026, 7, 26, 8, tzinfo=timezone.utc)
    repository = SQLiteSmartEntryRepository(
        database,
        clock=lambda: now,
        id_factory=lambda: "smart-draft-1",
    )
    try:
        created = repository.create_draft(
            "user-a",
            _payload(),
            expires_at="2026-08-25T08:00:00Z",
        )

        assert created.version == 1
        assert created.agent_status == "not_requested"
        assert repository.get_draft("user-b", created.id) is None
        assert repository.find_latest_draft("user-a", "2026-07-26") == created

        updated = repository.update_draft(
            "user-a",
            created.id,
            expected_version=1,
            payload=_payload(raw_text="早餐：燕麦 60g"),
        )
        assert updated.version == 2
        assert updated.payload.raw_text == "早餐：燕麦 60g"

        with pytest.raises(SmartEntryRepositoryError) as raised:
            repository.update_draft(
                "user-a",
                created.id,
                expected_version=1,
                payload=_payload(),
            )
        assert raised.value.code == "DRAFT_VERSION_CONFLICT"

        repository.delete_draft("user-a", created.id)
        assert repository.get_draft("user-a", created.id) is None
    finally:
        _cleanup(path)


def test_smart_entry_draft_expiry_and_malformed_payload_are_defensive():
    database, path = _database()
    current = [datetime(2026, 7, 26, 8, tzinfo=timezone.utc)]
    repository = SQLiteSmartEntryRepository(
        database,
        clock=lambda: current[0],
        id_factory=lambda: "smart-draft-2",
    )
    try:
        created = repository.create_draft(
            "user-a",
            _payload(),
            expires_at="2026-07-27T08:00:00Z",
        )
        current[0] += timedelta(days=2)
        assert repository.get_draft("user-a", created.id) is None

        current[0] -= timedelta(days=2)
        with database.transaction() as connection:
            connection.execute(
                """
                UPDATE record_drafts
                SET payload_json = '{"unexpected":true}'
                WHERE id = ?
                """,
                (created.id,),
            )
        with pytest.raises(SmartEntryRepositoryError) as raised:
            repository.get_draft("user-a", created.id)
        assert raised.value.code == "SMART_ENTRY_DRAFT_CORRUPT"
    finally:
        _cleanup(path)


def test_smart_entry_draft_bounds_raw_text_and_candidate_count():
    database, path = _database()
    repository = SQLiteSmartEntryRepository(database)
    try:
        with pytest.raises(SmartEntryRepositoryError) as raised:
            repository.create_draft(
                "user-a",
                _payload(raw_text="x" * 10_001),
                expires_at="2099-01-01T00:00:00Z",
            )
        assert raised.value.code == "SMART_ENTRY_TEXT_INVALID"

        payload = _payload()
        with pytest.raises(SmartEntryRepositoryError) as raised:
            repository.create_draft(
                "user-a",
                SmartEntryDraftPayload(
                    log_date=payload.log_date,
                    raw_text=payload.raw_text,
                    parser_version=payload.parser_version,
                    candidates=payload.candidates * 101,
                ),
                expires_at="2099-01-01T00:00:00Z",
            )
        assert raised.value.code == "SMART_ENTRY_CANDIDATES_INVALID"
    finally:
        _cleanup(path)
