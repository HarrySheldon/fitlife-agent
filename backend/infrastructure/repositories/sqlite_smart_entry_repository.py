from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
import json
from json import JSONDecodeError
from collections.abc import Callable
from uuid import uuid4

from backend.application.ports.smart_entry_repository import (
    SmartEntryDraft,
    SmartEntryDraftPayload,
    SmartEntryRepositoryError,
)
from backend.domain.smart_entry import CatalogChoice, ResolvedCandidate
from backend.infrastructure.sqlite.database import SQLiteDatabase


Clock = Callable[[], datetime]
IdFactory = Callable[[], str]

_MAX_RAW_TEXT = 10_000
_MAX_CANDIDATES = 100
_MAX_ASSUMPTIONS_PER_CANDIDATE = 20
_MAX_JSON_BYTES = 256 * 1024


class SQLiteSmartEntryRepository:
    def __init__(
        self,
        database: SQLiteDatabase,
        *,
        clock: Clock | None = None,
        id_factory: IdFactory | None = None,
    ) -> None:
        self.database = database
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: uuid4().hex)

    def create_draft(
        self,
        user_id: str,
        payload: SmartEntryDraftPayload,
        *,
        expires_at: str,
    ) -> SmartEntryDraft:
        serialized = _payload_json(payload)
        now_value = self._clock()
        now = _timestamp(now_value)
        expiry = _future_expiry(expires_at, now_value)
        draft_id = self._id_factory()
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO record_drafts (
                    id, user_id, kind, schema_version, payload_json, version,
                    agent_status, agent_metadata_json, expires_at,
                    created_at, updated_at
                ) VALUES (
                    ?, ?, 'smart_entry', 1, ?, 1,
                    'not_requested', '{}', ?, ?, ?
                )
                """,
                (draft_id, user_id, serialized, expiry, now, now),
            )
            row = connection.execute(
                "SELECT * FROM record_drafts WHERE id = ?",
                (draft_id,),
            ).fetchone()
        return _draft(row)

    def get_draft(
        self,
        user_id: str,
        draft_id: str,
    ) -> SmartEntryDraft | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM record_drafts
                WHERE id = ? AND user_id = ? AND kind = 'smart_entry'
                """,
                (draft_id, user_id),
            ).fetchone()
        if row is None or _expired(row["expires_at"], self._clock()):
            return None
        return _draft(row)

    def find_latest_draft(
        self,
        user_id: str,
        log_date: str,
    ) -> SmartEntryDraft | None:
        now = _timestamp(self._clock())
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM record_drafts
                WHERE user_id = ? AND kind = 'smart_entry'
                  AND json_extract(payload_json, '$.log_date') = ?
                  AND expires_at > ?
                ORDER BY updated_at DESC, created_at DESC, id DESC
                LIMIT 1
                """,
                (user_id, log_date, now),
            ).fetchone()
        return _draft(row) if row is not None else None

    def update_draft(
        self,
        user_id: str,
        draft_id: str,
        *,
        expected_version: int,
        payload: SmartEntryDraftPayload,
    ) -> SmartEntryDraft:
        serialized = _payload_json(payload)
        with self.database.transaction() as connection:
            now_value = self._clock()
            now = _timestamp(now_value)
            _require_draft(
                connection,
                user_id,
                draft_id,
                expected_version=expected_version,
                now=now_value,
            )
            cursor = connection.execute(
                """
                UPDATE record_drafts
                SET payload_json = ?, version = version + 1,
                    agent_status = 'not_requested',
                    agent_prompt_version = NULL,
                    agent_model = NULL,
                    agent_metadata_json = '{}',
                    updated_at = ?
                WHERE id = ? AND user_id = ? AND kind = 'smart_entry'
                  AND version = ? AND expires_at > ?
                """,
                (
                    serialized,
                    now,
                    draft_id,
                    user_id,
                    expected_version,
                    now,
                ),
            )
            if cursor.rowcount != 1:
                _require_draft(
                    connection,
                    user_id,
                    draft_id,
                    expected_version=expected_version,
                    now=now_value,
                )
                raise SmartEntryRepositoryError("DRAFT_UPDATE_FAILED")
            row = connection.execute(
                "SELECT * FROM record_drafts WHERE id = ?",
                (draft_id,),
            ).fetchone()
        return _draft(row)

    def delete_draft(self, user_id: str, draft_id: str) -> None:
        with self.database.transaction() as connection:
            _require_draft(
                connection,
                user_id,
                draft_id,
                expected_version=None,
                now=self._clock(),
            )
            connection.execute(
                """
                DELETE FROM record_drafts
                WHERE id = ? AND user_id = ? AND kind = 'smart_entry'
                """,
                (draft_id, user_id),
            )


def _payload_json(payload: SmartEntryDraftPayload) -> str:
    if (
        not isinstance(payload.raw_text, str)
        or not payload.raw_text.strip()
        or len(payload.raw_text) > _MAX_RAW_TEXT
    ):
        raise SmartEntryRepositoryError("SMART_ENTRY_TEXT_INVALID")
    try:
        date.fromisoformat(payload.log_date)
    except (TypeError, ValueError):
        raise SmartEntryRepositoryError("SMART_ENTRY_DATE_INVALID") from None
    if (
        not isinstance(payload.parser_version, str)
        or not payload.parser_version.strip()
        or len(payload.parser_version) > 100
    ):
        raise SmartEntryRepositoryError("SMART_ENTRY_PARSER_VERSION_INVALID")
    if not 1 <= len(payload.candidates) <= _MAX_CANDIDATES:
        raise SmartEntryRepositoryError("SMART_ENTRY_CANDIDATES_INVALID")
    if any(
        len(candidate.assumptions) > _MAX_ASSUMPTIONS_PER_CANDIDATE
        for candidate in payload.candidates
    ):
        raise SmartEntryRepositoryError("SMART_ENTRY_ASSUMPTIONS_INVALID")
    serialized = json.dumps(
        asdict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(serialized.encode("utf-8")) > _MAX_JSON_BYTES:
        raise SmartEntryRepositoryError("SMART_ENTRY_DRAFT_TOO_LARGE")
    return serialized


def _draft(row) -> SmartEntryDraft:
    try:
        payload_data = json.loads(row["payload_json"])
        metadata = json.loads(row["agent_metadata_json"])
        if not isinstance(payload_data, dict) or not isinstance(metadata, dict):
            raise TypeError
        candidates = tuple(
            _candidate(item) for item in payload_data["candidates"]
        )
        payload = SmartEntryDraftPayload(
            log_date=payload_data["log_date"],
            raw_text=payload_data["raw_text"],
            parser_version=payload_data["parser_version"],
            candidates=candidates,
        )
        _payload_json(payload)
    except (
        JSONDecodeError,
        KeyError,
        TypeError,
        SmartEntryRepositoryError,
        ValueError,
    ):
        raise SmartEntryRepositoryError("SMART_ENTRY_DRAFT_CORRUPT") from None
    return SmartEntryDraft(
        id=row["id"],
        user_id=row["user_id"],
        payload=payload,
        version=row["version"],
        agent_status=row["agent_status"],
        agent_prompt_version=row["agent_prompt_version"],
        agent_model=row["agent_model"],
        agent_metadata=metadata,
        expires_at=row["expires_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _candidate(value: object) -> ResolvedCandidate:
    if not isinstance(value, dict):
        raise TypeError
    data = dict(value)
    data["catalog_choices"] = tuple(
        CatalogChoice(
            id=item["id"],
            name=item["name"],
            source=item["source"],
            aliases=tuple(item.get("aliases", ())),
        )
        for item in data.get("catalog_choices", ())
    )
    data["issues"] = tuple(data.get("issues", ()))
    data["assumptions"] = tuple(data.get("assumptions", ()))
    return ResolvedCandidate(**data)


def _require_draft(
    connection,
    user_id: str,
    draft_id: str,
    *,
    expected_version: int | None,
    now: datetime,
):
    row = connection.execute(
        """
        SELECT * FROM record_drafts
        WHERE id = ? AND user_id = ? AND kind = 'smart_entry'
        """,
        (draft_id, user_id),
    ).fetchone()
    if row is None:
        raise SmartEntryRepositoryError("DRAFT_NOT_FOUND")
    if _expired(row["expires_at"], now):
        raise SmartEntryRepositoryError("DRAFT_EXPIRED")
    if expected_version is not None and row["version"] != expected_version:
        raise SmartEntryRepositoryError("DRAFT_VERSION_CONFLICT")
    return row


def _future_expiry(value: str, now: datetime) -> str:
    try:
        expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        raise SmartEntryRepositoryError("DRAFT_EXPIRY_INVALID") from None
    if expiry.tzinfo is None:
        raise SmartEntryRepositoryError("DRAFT_EXPIRY_INVALID")
    expiry = expiry.astimezone(timezone.utc)
    if expiry <= now.astimezone(timezone.utc):
        raise SmartEntryRepositoryError("DRAFT_EXPIRY_INVALID")
    return _timestamp(expiry)


def _expired(value: str, now: datetime) -> bool:
    try:
        expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return True
    return expiry <= now.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00",
        "Z",
    )
