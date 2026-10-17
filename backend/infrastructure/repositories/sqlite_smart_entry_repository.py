from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
import json
from json import JSONDecodeError
from collections.abc import Callable
from dataclasses import replace
import sqlite3
from uuid import uuid4

from backend.application.ports.smart_entry_repository import (
    ConfirmedSmartEntry,
    SmartEntryDraft,
    SmartEntryDraftPayload,
    SmartEntryRepositoryError,
)
from backend.domain.smart_entry import CatalogChoice, ResolvedCandidate, is_training_only_update
from backend.domain.entry_interaction import (EntryInteraction, EntryItem, EntryQuestion,
    EntryQuestionGroup, CatalogDependency, project_interaction)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.repositories.sqlite_daily_log import (
    ensure_daily_log,
)


Clock = Callable[[], datetime]
IdFactory = Callable[[], str]

_MAX_RAW_TEXT = 10_000
_MAX_CANDIDATES = 100
_MAX_ASSUMPTIONS_PER_CANDIDATE = 20
_MAX_JSON_BYTES = 256 * 1024
_CONFIRM_OPERATION = "smart_entry_confirm"


class SQLiteSmartEntryRepository:
    def list_entry_item_commits(self, user_id, draft_id):
        from backend.infrastructure.repositories.sqlite_entry_item_commits import _facts
        with self.database.connection() as connection:
            _require_draft(connection, user_id, draft_id, expected_version=None, now=self._clock())
            rows = connection.execute(
                'SELECT item_id, item_revision FROM entry_item_commits WHERE user_id=? AND draft_id=? ORDER BY item_id, item_revision',
                (user_id, draft_id)).fetchall()
            return _facts(connection, user_id, draft_id,
                          tuple((row['item_id'], row['item_revision']) for row in rows))

    def confirm_items(self, user_id, draft_id, **arguments):
        from backend.infrastructure.repositories.sqlite_entry_item_commits import confirm_items
        try:
            return confirm_items(self, user_id, draft_id, **arguments)
        except sqlite3.Error:
            raise SmartEntryRepositoryError('SMART_ENTRY_CONFIRM_FAILED') from None

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

    def read_interaction_draft(self, user_id: str, draft_id: str) -> SmartEntryDraft:
        """Owner-bound read which distinguishes expired drafts from missing ones."""
        with self.database.connection() as connection:
            row = _require_draft(connection, user_id, draft_id,
                                 expected_version=None, now=self._clock())
            return _draft(row)

    def get_interaction_command_result(
        self, user_id: str, draft_id: str, *, idempotency_key: str,
        request_fingerprint: str,
    ) -> SmartEntryDraft | None:
        """Read a receipt without preparing a command or granting write authority."""
        with self.database.connection() as connection:
            _require_draft(connection, user_id, draft_id,
                           expected_version=None, now=self._clock())
            receipt = connection.execute(
                'SELECT request_fingerprint, response_json FROM entry_interaction_commands WHERE draft_id = ? AND idempotency_key = ?',
                (draft_id, idempotency_key),
            ).fetchone()
            if receipt is None:
                return None
            if receipt['request_fingerprint'] != request_fingerprint:
                raise SmartEntryRepositoryError('IDEMPOTENCY_KEY_REUSED')
            return _command_snapshot(receipt['response_json'], user_id, draft_id)

    def execute_interaction_command(
        self, user_id: str, draft_id: str, *, expected_version: int,
        idempotency_key: str, request_fingerprint: str,
        transform: Callable[[SmartEntryDraft], SmartEntryDraftPayload],
    ) -> SmartEntryDraft:
        """Commit a trusted, pure application transform and its replay snapshot atomically.

        Model calls must finish before entering this seam. The supplied version
        then prevents a stale model result overwriting an intervening edit.
        """
        if type(expected_version) is not int or expected_version < 1:
            raise SmartEntryRepositoryError('DRAFT_VERSION_INVALID')
        if (not isinstance(idempotency_key, str) or not idempotency_key.strip()
                or len(idempotency_key) > 200 or not isinstance(request_fingerprint, str)
                or not request_fingerprint.strip() or len(request_fingerprint) > 200):
            raise SmartEntryRepositoryError('INTERACTION_COMMAND_INVALID')
        with self.database.transaction() as connection:
            now = self._clock()
            previous = _require_draft(connection, user_id, draft_id, expected_version=None, now=now)
            receipt = connection.execute(
                'SELECT request_fingerprint, response_json FROM entry_interaction_commands WHERE draft_id = ? AND idempotency_key = ?',
                (draft_id, idempotency_key),
            ).fetchone()
            if receipt is not None:
                if receipt['request_fingerprint'] != request_fingerprint:
                    raise SmartEntryRepositoryError('IDEMPOTENCY_KEY_REUSED')
                return _command_snapshot(receipt['response_json'], user_id, draft_id)
            if previous['version'] != expected_version:
                raise SmartEntryRepositoryError('DRAFT_VERSION_CONFLICT')
            current = _draft(previous)
            payload = transform(current)
            _protect_terminal_interaction(payload, current.payload)
            serialized = _payload_json(payload)
            # Decode with the same closed storage validator before persisting.
            check = dict(previous)
            check.update(payload_json=serialized, schema_version=2)
            _draft(check)
            connection.execute(
                'UPDATE record_drafts SET payload_json = ?, schema_version = 2, version = version + 1, updated_at = ? WHERE id = ? AND user_id = ? AND version = ?',
                (serialized, _timestamp(now), draft_id, user_id, expected_version),
            )
            row = connection.execute('SELECT * FROM record_drafts WHERE id = ?', (draft_id,)).fetchone()
            result = _draft(row)
            snapshot = _json(dict(row))
            if len(snapshot.encode('utf-8')) > 288 * 1024:
                raise SmartEntryRepositoryError('INTERACTION_RESPONSE_TOO_LARGE')
            connection.execute(
                'INSERT INTO entry_interaction_commands (draft_id, idempotency_key, request_fingerprint, response_json) VALUES (?, ?, ?, ?)',
                (draft_id, idempotency_key, request_fingerprint, snapshot),
            )
            return result

    def create_draft(
        self,
        user_id: str,
        payload: SmartEntryDraftPayload,
        *,
        expires_at: str,
    ) -> SmartEntryDraft:
        _payload_json(payload)
        payload = _storage_payload(payload)
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
                    ?, ?, 'smart_entry', 2, ?, 1,
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
        _payload_json(payload)
        with self.database.transaction() as connection:
            now_value = self._clock()
            now = _timestamp(now_value)
            previous = _require_draft(
                connection,
                user_id,
                draft_id,
                expected_version=expected_version,
                now=now_value,
            )
            old_payload = _draft(previous).payload
            _protect_terminal(payload, old_payload)
            if old_payload.interaction.active:
                payload = _training_storage_payload(payload, old_payload)
            else:
                payload = _storage_payload(payload, old_payload.interaction)
            serialized = _payload_json(payload)
            cursor = connection.execute(
                """
                UPDATE record_drafts
                SET payload_json = ?, schema_version = 2, version = version + 1,
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

    def save_analysis(
        self,
        user_id: str,
        draft_id: str,
        *,
        expected_version: int,
        payload: SmartEntryDraftPayload,
        prompt_version: str,
        model: str,
        metadata: dict[str, object],
    ) -> SmartEntryDraft:
        return self._update_agent_state(
            user_id,
            draft_id,
            expected_version=expected_version,
            payload_json=_payload_json(payload),
            status="completed",
            prompt_version=prompt_version,
            model=model,
            metadata=metadata,
        )

    def mark_agent_failed(
        self,
        user_id: str,
        draft_id: str,
        *,
        expected_version: int,
        prompt_version: str,
        model: str | None,
        metadata: dict[str, object],
    ) -> SmartEntryDraft:
        return self._update_agent_state(
            user_id,
            draft_id,
            expected_version=expected_version,
            payload_json=None,
            status="failed",
            prompt_version=prompt_version,
            model=model,
            metadata=metadata,
        )

    def _update_agent_state(
        self,
        user_id: str,
        draft_id: str,
        *,
        expected_version: int,
        payload_json: str | None,
        status: str,
        prompt_version: str,
        model: str | None,
        metadata: dict[str, object],
    ) -> SmartEntryDraft:
        metadata_json = _metadata_json(metadata)
        with self.database.transaction() as connection:
            now_value = self._clock()
            now = _timestamp(now_value)
            previous = _require_draft(
                connection,
                user_id,
                draft_id,
                expected_version=expected_version,
                now=now_value,
            )
            old_payload = _draft(previous).payload
            next_payload = old_payload if payload_json is None else _payload_from_json(payload_json)
            _protect_terminal(next_payload, old_payload)
            payload_json = _payload_json(_storage_payload(next_payload, old_payload.interaction))
            cursor = connection.execute(
                """
                UPDATE record_drafts
                SET payload_json = ?, schema_version = 2,
                    version = version + 1,
                    agent_status = ?,
                    agent_prompt_version = ?,
                    agent_model = ?,
                    agent_metadata_json = ?,
                    updated_at = ?
                WHERE id = ? AND user_id = ? AND kind = 'smart_entry'
                  AND version = ? AND expires_at > ?
                """,
                (
                    payload_json,
                    status,
                    prompt_version,
                    model,
                    metadata_json,
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

    def confirm(
        self,
        user_id: str,
        draft_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
        request_fingerprint: str,
        timezone_name: str = "UTC",
    ) -> ConfirmedSmartEntry:
        try:
            with self.database.transaction() as connection:
                existing = connection.execute(
                    """
                    SELECT response_json FROM idempotency_keys
                    WHERE user_id = ? AND operation = ?
                      AND idempotency_key = ?
                    """,
                    (user_id, _CONFIRM_OPERATION, idempotency_key),
                ).fetchone()
                if existing is not None:
                    return _replay_confirmation(
                        existing["response_json"],
                        request_fingerprint,
                    )

                now_value = self._clock()
                now = _timestamp(now_value)
                row = _require_draft(
                    connection,
                    user_id,
                    draft_id,
                    expected_version=expected_version,
                    now=now_value,
                )
                draft = _draft(row)
                selected = tuple(
                    item for item in draft.payload.candidates if item.selected
                )
                active = draft.payload.interaction.active and any(
                    candidate.kind == 'food' for candidate in draft.payload.candidates)
                if active:
                    selected = tuple(item for item in selected if item.kind != 'food')
                    if not selected:
                        raise SmartEntryRepositoryError('INTERACTION_CONFIRM_ITEMS_REQUIRED')
                _validate_selected_candidates(selected)
                ensure_daily_log(
                    connection,
                    self._id_factory,
                    user_id,
                    draft.payload.log_date,
                    now,
                    timezone_name,
                )
                meal_ids = self._insert_meals(
                    connection,
                    user_id,
                    draft.payload.log_date,
                    selected,
                    now,
                )
                session_id = self._insert_workout(
                    connection,
                    user_id,
                    draft.payload.log_date,
                    selected,
                    now,
                )
                if meal_ids:
                    connection.execute(
                        """
                        UPDATE daily_logs
                        SET planned_meal_count = MAX(
                                planned_meal_count,
                                (
                                    SELECT COUNT(*) FROM meals
                                    WHERE user_id = ? AND log_date = ?
                                )
                            ),
                            updated_at = ?
                        WHERE user_id = ? AND log_date = ?
                        """,
                        (
                            user_id,
                            draft.payload.log_date,
                            now,
                            user_id,
                            draft.payload.log_date,
                        ),
                    )
                confirmed = ConfirmedSmartEntry(
                    draft_id=draft.id,
                    log_date=draft.payload.log_date,
                    meal_ids=meal_ids,
                    training_session_id=session_id,
                )
                response_json = json.dumps(
                    {
                        "request_fingerprint": request_fingerprint,
                        "response": asdict(confirmed),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                connection.execute(
                    """
                    INSERT INTO idempotency_keys (
                        user_id, operation, idempotency_key,
                        response_json, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        _CONFIRM_OPERATION,
                        idempotency_key,
                        response_json,
                        now,
                    ),
                )
                if active:
                    consumed = {item.id for item in selected}
                    payload = replace(draft.payload, candidates=tuple(
                        item for item in draft.payload.candidates if item.id not in consumed))
                    connection.execute('UPDATE record_drafts SET payload_json=?, version=version+1, updated_at=? WHERE id=? AND user_id=?',
                                       (_payload_json(payload), now, draft_id, user_id))
                else:
                    connection.execute(
                        "DELETE FROM record_drafts WHERE id = ? AND user_id = ? AND kind = 'smart_entry'",
                        (draft_id, user_id),
                    )
            return confirmed
        except sqlite3.Error:
            raise SmartEntryRepositoryError(
                "SMART_ENTRY_CONFIRM_FAILED"
            ) from None

    def _insert_meals(
        self,
        connection,
        user_id: str,
        log_date: str,
        selected: tuple[ResolvedCandidate, ...],
        now: str,
    ) -> tuple[str, ...]:
        grouped: dict[str, list[ResolvedCandidate]] = {}
        for candidate in selected:
            if candidate.kind == "food":
                grouped.setdefault(
                    candidate.meal_context or "other",
                    [],
                ).append(candidate)
        if not grouped:
            return ()
        row = connection.execute(
            """
            SELECT COALESCE(MAX(position), 0) AS position
            FROM meals WHERE user_id = ? AND log_date = ?
            """,
            (user_id, log_date),
        ).fetchone()
        position = int(row["position"])
        meal_ids: list[str] = []
        for meal_context, candidates in grouped.items():
            position += 1
            meal_id = self._id_factory()
            connection.execute(
                """
                INSERT INTO meals (
                    id, user_id, log_date, name, meal_type, position,
                    entry_method, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'smart_entry', ?, ?)
                """,
                (
                    meal_id,
                    user_id,
                    log_date,
                    _meal_name(meal_context),
                    _meal_type(meal_context),
                    position,
                    now,
                    now,
                ),
            )
            meal_ids.append(meal_id)
            for candidate in candidates:
                _require_catalog_visibility(
                    connection,
                    user_id,
                    "food_catalog",
                    candidate.selected_catalog_id,
                )
                values = candidate.values
                connection.execute(
                    """
                    INSERT INTO meal_items (
                        id, meal_id, catalog_food_id, food_name,
                        amount, unit, basis_type, calories, carbs,
                        protein, fat, source, is_estimate,
                        uncertainty_json, assumptions_json,
                        provenance_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._id_factory(),
                        meal_id,
                        candidate.selected_catalog_id,
                        values["name"],
                        values["amount"],
                        values["unit"],
                        values["basis_type"],
                        values["calories"],
                        values["carbs"],
                        values["protein"],
                        values["fat"],
                        values.get("source", "user_custom"),
                        int(bool(values.get("is_estimate"))),
                        _json(values.get("uncertainty", {})),
                        _json(candidate.assumptions),
                        _json(candidate.provenance),
                        now,
                    ),
                )
                if candidate.selected_catalog_id is not None:
                    _record_usage(
                        connection,
                        self._id_factory,
                        user_id,
                        food_id=candidate.selected_catalog_id,
                        exercise_id=None,
                        now=now,
                    )
        return tuple(meal_ids)

    def _insert_workout(
        self,
        connection,
        user_id: str,
        log_date: str,
        selected: tuple[ResolvedCandidate, ...],
        now: str,
    ) -> str | None:
        strength = tuple(item for item in selected if item.kind == "strength")
        cardio = tuple(item for item in selected if item.kind == "cardio")
        if not strength and not cardio:
            return None
        estimated = [
            float(item.values["estimated_calories"])
            for item in (*strength, *cardio)
            if item.values.get("estimated_calories") is not None
        ]
        session_id = self._id_factory()
        connection.execute(
            """
            INSERT INTO training_sessions (
                id, user_id, log_date, title, started_at,
                duration_min, intensity, entry_method,
                estimated_calories, estimate_json, created_at, updated_at
            ) VALUES (
                ?, ?, ?, 'Smart entry workout', NULL,
                NULL, NULL, 'smart_entry', ?, ?, ?, ?
            )
            """,
            (
                session_id,
                user_id,
                log_date,
                round(sum(estimated), 1) if estimated else None,
                _json({"contains_estimates": bool(estimated)}),
                now,
                now,
            ),
        )
        for position, candidate in enumerate(strength, start=1):
            _require_catalog_visibility(
                connection,
                user_id,
                "exercise_catalog",
                candidate.selected_catalog_id,
            )
            values = candidate.values
            exercise_id = self._id_factory()
            connection.execute(
                """
                INSERT INTO strength_exercises (
                    id, session_id, catalog_exercise_id, exercise_name,
                    primary_muscle, secondary_muscles_json,
                    estimated_calories, estimate_json,
                    provenance_json, position
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    exercise_id,
                    session_id,
                    candidate.selected_catalog_id,
                    values["name"],
                    values["primary_muscle"],
                    _json(values.get("secondary_muscles", ())),
                    values.get("estimated_calories"),
                    _json(
                        {
                            "is_estimate": bool(
                                values.get("estimated_calories") is not None
                            ),
                            "method": values.get("estimate_method"),
                        }
                    ),
                    _json(candidate.provenance),
                    position,
                ),
            )
            for set_number in range(1, int(values["set_count"]) + 1):
                connection.execute(
                    """
                    INSERT INTO strength_sets (
                        id, strength_exercise_id, set_number,
                        reps, load_kg, bodyweight
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._id_factory(),
                        exercise_id,
                        set_number,
                        values["reps"],
                        values.get("load_kg"),
                        int(bool(values.get("bodyweight"))),
                    ),
                )
            if candidate.selected_catalog_id is not None:
                _record_usage(
                    connection,
                    self._id_factory,
                    user_id,
                    food_id=None,
                    exercise_id=candidate.selected_catalog_id,
                    now=now,
                )
        for position, candidate in enumerate(cardio, start=1):
            _require_catalog_visibility(
                connection,
                user_id,
                "exercise_catalog",
                candidate.selected_catalog_id,
            )
            values = candidate.values
            connection.execute(
                """
                INSERT INTO cardio_items (
                    id, session_id, catalog_exercise_id, activity_name,
                    duration_min, device_calories, met,
                    estimated_calories, estimate_json,
                    provenance_json, position
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._id_factory(),
                    session_id,
                    candidate.selected_catalog_id,
                    values["name"],
                    values["duration_min"],
                    values.get("device_calories"),
                    values.get("met"),
                    values.get("estimated_calories"),
                    _json(
                        {
                            "is_estimate": bool(values.get("is_estimate")),
                            "method": values.get("estimate_method"),
                        }
                    ),
                    _json(candidate.provenance),
                    position,
                ),
            )
            if candidate.selected_catalog_id is not None:
                _record_usage(
                    connection,
                    self._id_factory,
                    user_id,
                    food_id=None,
                    exercise_id=candidate.selected_catalog_id,
                    now=now,
                )
        return session_id


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


def _protect_terminal(payload: SmartEntryDraftPayload, previous: SmartEntryDraftPayload) -> None:
    old_candidates = {candidate.id: candidate for candidate in previous.candidates}
    candidates = {candidate.id: candidate for candidate in payload.candidates}
    for item in previous.interaction.items:
        if item.state in ('saved', 'discarded') and candidates.get(item.item_id) != old_candidates[item.item_id]:
            raise SmartEntryRepositoryError('ITEM_NOT_EDITABLE')


def _protect_terminal_interaction(payload: SmartEntryDraftPayload, previous: SmartEntryDraftPayload) -> None:
    _protect_terminal(payload, previous)
    items = {item.item_id: item for item in payload.interaction.items}
    for item in previous.interaction.items:
        if item.state in ('saved', 'discarded') and items.get(item.item_id) != item:
            raise SmartEntryRepositoryError('ITEM_NOT_EDITABLE')


def _command_snapshot(serialized: str, user_id: str, draft_id: str) -> SmartEntryDraft:
    try:
        if not isinstance(serialized, str) or len(serialized.encode('utf-8')) > 288 * 1024:
            raise ValueError
        row = json.loads(serialized)
        fields = {'id', 'user_id', 'kind', 'schema_version', 'payload_json', 'version',
                  'agent_status', 'agent_prompt_version', 'agent_model',
                  'agent_metadata_json', 'expires_at', 'created_at', 'updated_at'}
        if (not isinstance(row, dict) or set(row) != fields
                or row.get('id') != draft_id or row.get('user_id') != user_id
                or row.get('kind') != 'smart_entry' or type(row.get('version')) is not int
                or row['version'] < 1 or type(row.get('schema_version')) is not int
                or row['schema_version'] != 2):
            raise ValueError
        if row['agent_status'] not in ('not_requested', 'running', 'completed', 'failed'):
            raise ValueError
        for key in ('agent_model', 'agent_prompt_version'):
            if row[key] is not None and not isinstance(row[key], str):
                raise ValueError
        for key in ('expires_at', 'created_at', 'updated_at', 'payload_json', 'agent_metadata_json'):
            if not isinstance(row[key], str) or not row[key].strip():
                raise ValueError
        expiry = datetime.fromisoformat(row['expires_at'].replace('Z', '+00:00'))
        if expiry.tzinfo is None:
            raise ValueError
        return _draft(row)
    except (ValueError, TypeError, KeyError, RecursionError):
        raise SmartEntryRepositoryError('IDEMPOTENCY_RESPONSE_CORRUPT') from None


def _training_storage_payload(payload: SmartEntryDraftPayload, previous: SmartEntryDraftPayload) -> SmartEntryDraftPayload:
    if ((payload.log_date, payload.raw_text, payload.parser_version)
            != (previous.log_date, previous.raw_text, previous.parser_version)
            or payload.interaction != previous.interaction
            or not is_training_only_update(previous.candidates, payload.candidates)):
        raise SmartEntryRepositoryError('INTERACTION_ACTIVE')
    foods = {item.id: item for item in previous.candidates if item.kind == 'food'}
    return replace(payload, interaction=previous.interaction,
        candidates=tuple(foods.get(item.id, item) for item in payload.candidates))


def _storage_payload(payload: SmartEntryDraftPayload, previous: EntryInteraction | None = None) -> SmartEntryDraftPayload:
    interaction = previous or payload.interaction or project_interaction(payload.candidates)
    if previous is not None and previous.active:
        raise SmartEntryRepositoryError('INTERACTION_ACTIVE')
    projected = project_interaction(payload.candidates, schema_version=2)
    old_items = {item.item_id: item for item in interaction.items}
    candidates = {candidate.id: candidate for candidate in payload.candidates if candidate.kind == 'food'}
    for item in interaction.items:
        if item.state in ('saved', 'discarded'):
            candidate = candidates.get(item.item_id)
            if candidate is None or candidate.values != item.values:
                raise SmartEntryRepositoryError('ITEM_NOT_EDITABLE')
    items = []
    for item in projected.items:
        old = old_items.get(item.item_id)
        if old is not None:
            if old.values == item.values:
                item = old
            else:
                item = replace(item, revision=old.revision + 1)
        items.append(item)
    return replace(payload, interaction=replace(interaction, schema_version=2, items=tuple(items)))


def _interaction(value: object, candidates: tuple[ResolvedCandidate, ...]) -> EntryInteraction:
    if value is None:
        return project_interaction(candidates)
    required = {'schema_version', 'clarification_rounds', 'items', 'active'}
    optional = {'status', 'question_groups', 'dependencies', 'run_ids'}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - optional:
        raise TypeError
    if not isinstance(value['items'], list):
        raise TypeError
    items = []
    for data in value['items']:
        if not isinstance(data, dict) or set(data) != {'item_id', 'revision', 'state', 'values', 'sources', 'missing_fields', 'assumptions'}:
            raise TypeError
        if not isinstance(data['values'], dict) or not isinstance(data['sources'], dict):
            raise TypeError
        for key in ('missing_fields', 'assumptions'):
            if not isinstance(data[key], list) or any(not isinstance(item, str) for item in data[key]):
                raise TypeError
        items.append(EntryItem(**{**data, 'missing_fields': tuple(data['missing_fields']), 'assumptions': tuple(data['assumptions'])}))
    groups = []
    for data in value.get('question_groups', []):
        if not isinstance(data, dict) or set(data) != {'group_id', 'asked_at', 'expected_version', 'questions', 'answered'}:
            raise TypeError
        questions = []
        for question in data['questions']:
            if not isinstance(question, dict) or set(question) != {'item_id', 'field', 'portion_options'}:
                raise TypeError
            if not isinstance(question['portion_options'], list):
                raise TypeError
            questions.append(EntryQuestion(**{**question, 'portion_options': tuple(question['portion_options'])}))
        groups.append(EntryQuestionGroup(**{**data, 'questions': tuple(questions)}))
    dependencies = []
    for data in value.get('dependencies', []):
        if not isinstance(data, dict) or set(data) != {'item_id', 'catalog_id', 'signature'}:
            raise TypeError
        dependencies.append(CatalogDependency(**data))
    for key in ('question_groups', 'dependencies', 'run_ids'):
        if key in value and not isinstance(value[key], list):
            raise TypeError
    interaction = EntryInteraction(**{**value, 'items': tuple(items),
        'question_groups': tuple(groups), 'dependencies': tuple(dependencies),
        'run_ids': tuple(value.get('run_ids', ()))})
    food_candidates = {candidate.id: candidate for candidate in candidates if candidate.kind == 'food'}
    if len(food_candidates) != len(interaction.items) or {item.item_id for item in interaction.items} != set(food_candidates):
        raise TypeError
    if any(item.values != food_candidates[item.item_id].values for item in interaction.items):
        raise TypeError
    return interaction


def _payload_from_json(serialized: str) -> SmartEntryDraftPayload:
    data = json.loads(serialized)
    candidates = tuple(_candidate(item) for item in data['candidates'])
    return SmartEntryDraftPayload(data['log_date'], data['raw_text'], data['parser_version'], candidates)


def _metadata_json(value: dict[str, object]) -> str:
    if not isinstance(value, dict):
        raise SmartEntryRepositoryError("SMART_ENTRY_AGENT_METADATA_INVALID")
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(serialized.encode("utf-8")) > 32 * 1024:
        raise SmartEntryRepositoryError("SMART_ENTRY_AGENT_METADATA_INVALID")
    return serialized


def _validate_selected_candidates(
    candidates: tuple[ResolvedCandidate, ...],
) -> None:
    if not candidates:
        raise SmartEntryRepositoryError("SMART_ENTRY_SELECTION_REQUIRED")
    for candidate in candidates:
        if candidate.issues:
            raise SmartEntryRepositoryError("SMART_ENTRY_DRAFT_INCOMPLETE")
        values = candidate.values
        is_agent_value = (
            values.get("source") == "agent_estimate"
            or candidate.provenance.get("source") == "agent_estimate"
        )
        if is_agent_value and not candidate.agent_estimate_accepted:
            raise SmartEntryRepositoryError(
                "SMART_ENTRY_AGENT_ESTIMATE_NOT_ACCEPTED"
            )
        if candidate.kind == "food":
            _require_values(
                values,
                (
                    "name",
                    "amount",
                    "unit",
                    "basis_type",
                    "calories",
                    "carbs",
                    "protein",
                    "fat",
                ),
            )
            if not _positive(values["amount"]):
                raise SmartEntryRepositoryError("SMART_ENTRY_DRAFT_INCOMPLETE")
            if any(
                not _nonnegative(values[key])
                for key in ("calories", "carbs", "protein", "fat")
            ):
                raise SmartEntryRepositoryError("SMART_ENTRY_DRAFT_INCOMPLETE")
        elif candidate.kind == "strength":
            _require_values(
                values,
                ("name", "primary_muscle", "set_count", "reps"),
            )
            if not _positive_integer(values["set_count"]) or not _positive_integer(
                values["reps"]
            ):
                raise SmartEntryRepositoryError("SMART_ENTRY_DRAFT_INCOMPLETE")
        elif candidate.kind == "cardio":
            _require_values(
                values,
                ("name", "primary_muscle", "duration_min"),
            )
            if not _positive(values["duration_min"]):
                raise SmartEntryRepositoryError("SMART_ENTRY_DRAFT_INCOMPLETE")
            if not (
                _nonnegative(values.get("device_calories"))
                or _positive(values.get("met"))
            ):
                raise SmartEntryRepositoryError("SMART_ENTRY_DRAFT_INCOMPLETE")
        else:
            raise SmartEntryRepositoryError("SMART_ENTRY_DRAFT_INCOMPLETE")


def _require_values(values: dict[str, object], keys: tuple[str, ...]) -> None:
    if any(
        key not in values
        or values[key] is None
        or (isinstance(values[key], str) and not values[key].strip())
        for key in keys
    ):
        raise SmartEntryRepositoryError("SMART_ENTRY_DRAFT_INCOMPLETE")


def _positive(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and float(value) > 0
    )


def _nonnegative(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and float(value) >= 0
    )


def _positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _require_catalog_visibility(
    connection,
    user_id: str,
    table: str,
    catalog_id: str | None,
) -> None:
    if catalog_id is None:
        return
    if table not in {"food_catalog", "exercise_catalog"}:
        raise AssertionError("unsupported catalog table")
    row = connection.execute(
        f"""
        SELECT id FROM {table}
        WHERE id = ? AND active = 1
          AND (owner_user_id IS NULL OR owner_user_id = ?)
        """,
        (catalog_id, user_id),
    ).fetchone()
    if row is None:
        raise SmartEntryRepositoryError("SMART_ENTRY_CATALOG_NOT_VISIBLE")


def _record_usage(
    connection,
    id_factory: IdFactory,
    user_id: str,
    *,
    food_id: str | None,
    exercise_id: str | None,
    now: str,
) -> None:
    connection.execute(
        """
        INSERT INTO catalog_usage (
            id, user_id, food_id, exercise_id, use_count, last_used_at
        ) VALUES (?, ?, ?, ?, 1, ?)
        ON CONFLICT DO UPDATE SET
            use_count = catalog_usage.use_count + 1,
            last_used_at = excluded.last_used_at
        """,
        (id_factory(), user_id, food_id, exercise_id, now),
    )


def _meal_type(value: str) -> str:
    return value if value in {"breakfast", "lunch", "dinner", "snack"} else "custom"


def _meal_name(value: str) -> str:
    return {
        "breakfast": "Breakfast",
        "lunch": "Lunch",
        "dinner": "Dinner",
        "snack": "Snack",
        "other": "Meal",
    }.get(value, "Meal")


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _replay_confirmation(
    response_json: str,
    request_fingerprint: str,
) -> ConfirmedSmartEntry:
    try:
        stored = json.loads(response_json)
        if stored.get("request_fingerprint") != request_fingerprint:
            raise SmartEntryRepositoryError("IDEMPOTENCY_KEY_REUSED")
        response = stored["response"]
        return replace(
            ConfirmedSmartEntry(
                draft_id=response["draft_id"],
                log_date=response["log_date"],
                meal_ids=tuple(response["meal_ids"]),
                training_session_id=response["training_session_id"],
            ),
            replayed=True,
        )
    except SmartEntryRepositoryError:
        raise
    except (JSONDecodeError, KeyError, TypeError):
        raise SmartEntryRepositoryError("IDEMPOTENCY_RESPONSE_CORRUPT") from None


def _draft(row) -> SmartEntryDraft:
    try:
        if not isinstance(row['payload_json'], str):
            raise TypeError
        if len(row['payload_json'].encode('utf-8')) > _MAX_JSON_BYTES:
            raise ValueError
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
            interaction=_interaction(payload_data.get('interaction'), candidates),
        )
        if row['schema_version'] == 2 and (payload_data.get('interaction') is None or payload.interaction.schema_version != 2):
            raise ValueError
        _payload_json(payload)
    except (
        JSONDecodeError,
        KeyError,
        TypeError,
        SmartEntryRepositoryError,
        ValueError,
        RecursionError,
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
    if not isinstance(value.get('values'), dict) or not isinstance(value.get('provenance'), dict):
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
