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
from backend.domain.smart_entry import CatalogChoice, ResolvedCandidate
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
                SET payload_json = COALESCE(?, payload_json),
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
                connection.execute(
                    """
                    DELETE FROM record_drafts
                    WHERE id = ? AND user_id = ? AND kind = 'smart_entry'
                    """,
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
