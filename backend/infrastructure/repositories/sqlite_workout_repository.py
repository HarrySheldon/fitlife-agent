from __future__ import annotations

import json
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import date, datetime, timezone
from uuid import uuid4

from backend.application.ports.workout_repository import (
    CardioItemSnapshot,
    ConfirmedWorkout,
    CustomExerciseSnapshot,
    StrengthExerciseSnapshot,
    WorkoutDraft,
    WorkoutDraftInput,
    WorkoutDraftPayload,
    WorkoutRepositoryError,
)
from backend.domain.workouts import (
    StrengthSet,
    WorkoutDomainError,
    cardio_calories,
    strength_calories,
)
from backend.infrastructure.repositories.sqlite_exercise_catalog_repository import (
    _replace_search,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase


Clock = Callable[[], datetime]
IdFactory = Callable[[], str]
_CONFIRM_OPERATION = "workout_draft_confirm"


class SQLiteWorkoutRepository:
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
        payload: WorkoutDraftInput,
        expires_at: str,
    ) -> WorkoutDraft:
        draft_id = self._id_factory()
        with self.database.transaction() as connection:
            now_value = self._clock()
            now = _timestamp(now_value)
            expiry = _future_expiry(expires_at, now_value)
            resolved = _resolve_payload(connection, user_id, payload)
            connection.execute(
                """
                INSERT INTO record_drafts (
                    id, user_id, kind, schema_version, payload_json, version,
                    agent_status, expires_at, created_at, updated_at
                ) VALUES (
                    ?, ?, 'workout', 1, ?, 1, 'not_requested', ?, ?, ?
                )
                """,
                (draft_id, user_id, _payload_json(resolved), expiry, now, now),
            )
        return WorkoutDraft(
            id=draft_id,
            user_id=user_id,
            payload=resolved,
            version=1,
            expires_at=expiry,
            created_at=now,
            updated_at=now,
        )

    def get_draft(
        self,
        user_id: str,
        draft_id: str,
    ) -> WorkoutDraft | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM record_drafts
                WHERE id = ? AND user_id = ? AND kind = 'workout'
                """,
                (draft_id, user_id),
            ).fetchone()
        if row is None or _expired(row["expires_at"], self._clock()):
            return None
        return _draft(row)

    def update_draft(
        self,
        user_id: str,
        draft_id: str,
        *,
        expected_version: int,
        payload: WorkoutDraftInput,
    ) -> WorkoutDraft:
        with self.database.transaction() as connection:
            now_value = self._clock()
            now = _timestamp(now_value)
            _require_draft(
                connection,
                user_id,
                draft_id,
                expected_version,
                now_value,
            )
            resolved = _resolve_payload(connection, user_id, payload)
            cursor = connection.execute(
                """
                UPDATE record_drafts
                SET payload_json = ?, version = version + 1, updated_at = ?
                WHERE id = ? AND user_id = ? AND kind = 'workout'
                  AND version = ? AND expires_at > ?
                """,
                (
                    _payload_json(resolved),
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
                    expected_version,
                    now_value,
                )
                raise WorkoutRepositoryError("DRAFT_UPDATE_FAILED")
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
                None,
                self._clock(),
            )
            connection.execute(
                """
                DELETE FROM record_drafts
                WHERE id = ? AND user_id = ? AND kind = 'workout'
                """,
                (draft_id, user_id),
            )

    def confirm(
        self,
        user_id: str,
        draft_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> ConfirmedWorkout:
        with self.database.transaction() as connection:
            existing = connection.execute(
                """
                SELECT response_json FROM idempotency_keys
                WHERE user_id = ? AND operation = ? AND idempotency_key = ?
                """,
                (user_id, _CONFIRM_OPERATION, idempotency_key),
            ).fetchone()
            if existing is not None:
                return _replay(existing["response_json"], request_fingerprint)

            now_value = self._clock()
            now = _timestamp(now_value)
            row = _require_draft(
                connection,
                user_id,
                draft_id,
                expected_version,
                now_value,
            )
            draft = _draft(row)
            if (
                not draft.payload.strength_exercises
                and not draft.payload.cardio_items
            ):
                raise WorkoutRepositoryError("DRAFT_INCOMPLETE")
            _ensure_daily_log(
                connection,
                self._id_factory,
                user_id,
                draft.payload.log_date,
                now,
            )
            session_id = self._id_factory()
            connection.execute(
                """
                INSERT INTO training_sessions (
                    id, user_id, log_date, title, started_at, duration_min,
                    intensity, entry_method, estimated_calories, estimate_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'form', ?, ?, ?, ?)
                """,
                (
                    session_id,
                    user_id,
                    draft.payload.log_date,
                    draft.payload.title,
                    draft.payload.started_at,
                    draft.payload.duration_min,
                    draft.payload.intensity,
                    draft.payload.estimated_calories,
                    json.dumps(
                        {
                            **draft.payload.estimate,
                            "weight_kg_snapshot": (
                                draft.payload.weight_kg_snapshot
                            ),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    now,
                    now,
                ),
            )
            for position, item in enumerate(
                draft.payload.strength_exercises,
                start=1,
            ):
                exercise_id = _confirmed_exercise_id(
                    connection,
                    self._id_factory,
                    user_id,
                    item.catalog_exercise_id,
                    item.custom_exercise,
                    now,
                )
                strength_id = self._id_factory()
                connection.execute(
                    """
                    INSERT INTO strength_exercises (
                        id, session_id, catalog_exercise_id, exercise_name,
                        primary_muscle, secondary_muscles_json,
                        provenance_json, position
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        strength_id,
                        session_id,
                        exercise_id,
                        item.exercise_name,
                        item.primary_muscle,
                        json.dumps(
                            item.secondary_muscles,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        json.dumps(
                            item.provenance,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        position,
                    ),
                )
                for strength_set in item.sets:
                    connection.execute(
                        """
                        INSERT INTO strength_sets (
                            id, strength_exercise_id, set_number, reps,
                            load_kg, bodyweight
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            self._id_factory(),
                            strength_id,
                            strength_set.set_number,
                            strength_set.reps,
                            strength_set.load_kg,
                            int(strength_set.bodyweight),
                        ),
                    )
                _usage(
                    connection,
                    self._id_factory,
                    user_id,
                    exercise_id,
                    now,
                )
            for position, item in enumerate(
                draft.payload.cardio_items,
                start=1,
            ):
                exercise_id = _confirmed_exercise_id(
                    connection,
                    self._id_factory,
                    user_id,
                    item.catalog_exercise_id,
                    item.custom_exercise,
                    now,
                )
                connection.execute(
                    """
                    INSERT INTO cardio_items (
                        id, session_id, catalog_exercise_id, activity_name,
                        duration_min, device_calories, met,
                        estimated_calories, estimate_json, provenance_json,
                        position
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._id_factory(),
                        session_id,
                        exercise_id,
                        item.activity_name,
                        item.duration_min,
                        item.device_calories,
                        item.met,
                        item.estimated_calories,
                        json.dumps(
                            {
                                **item.estimate,
                                "is_estimate": item.is_estimate,
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        json.dumps(
                            item.provenance,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        position,
                    ),
                )
                _usage(
                    connection,
                    self._id_factory,
                    user_id,
                    exercise_id,
                    now,
                )
            confirmed = _load_session(connection, session_id)
            response = json.dumps(
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
                    user_id, operation, idempotency_key, response_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    _CONFIRM_OPERATION,
                    idempotency_key,
                    response,
                    now,
                ),
            )
            connection.execute(
                """
                DELETE FROM record_drafts
                WHERE id = ? AND user_id = ? AND kind = 'workout'
                """,
                (draft_id, user_id),
            )
        return confirmed

    def list_sessions(
        self,
        user_id: str,
        log_date: str,
    ) -> tuple[ConfirmedWorkout, ...]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT id FROM training_sessions
                WHERE user_id = ? AND log_date = ?
                ORDER BY created_at, id
                """,
                (user_id, log_date),
            ).fetchall()
            return tuple(_load_session(connection, row["id"]) for row in rows)


def _resolve_payload(
    connection,
    user_id: str,
    payload: WorkoutDraftInput,
) -> WorkoutDraftPayload:
    _validate_header(payload)
    weight = _effective_weight(connection, user_id, payload.log_date)
    strength = tuple(
        _strength_snapshot(connection, user_id, item)
        for item in payload.strength_exercises
    )
    cardio = tuple(
        _cardio_snapshot(connection, user_id, item, weight)
        for item in payload.cardio_items
    )
    try:
        strength_estimate = (
            strength_calories(
                duration_min=payload.duration_min,
                intensity=payload.intensity,
                weight_kg=weight,
            )
            if strength
            else None
        )
    except WorkoutDomainError as error:
        raise WorkoutRepositoryError(error.code) from None
    total_parts = [item.estimated_calories for item in cardio]
    if strength_estimate is not None:
        total_parts.append(strength_estimate.calories)
    estimated_calories = (
        round(sum(total_parts), 1) if total_parts else None
    )
    return WorkoutDraftPayload(
        log_date=payload.log_date,
        title=payload.title.strip(),
        started_at=payload.started_at,
        duration_min=payload.duration_min,
        intensity=payload.intensity,
        entry_method="form",
        weight_kg_snapshot=weight,
        estimated_calories=estimated_calories,
        estimate={
            "contains_estimates": bool(
                strength_estimate is not None
                or any(item.is_estimate for item in cardio)
            ),
            "strength": (
                asdict(strength_estimate)
                if strength_estimate is not None
                else None
            ),
        },
        strength_exercises=strength,
        cardio_items=cardio,
    )


def _strength_snapshot(connection, user_id: str, item) -> StrengthExerciseSnapshot:
    definition, provenance, custom = _exercise(
        connection,
        user_id,
        item.catalog_exercise_id,
        item.custom_exercise,
        required_type="strength",
    )
    if not item.sets:
        raise WorkoutRepositoryError("STRENGTH_SETS_REQUIRED")
    numbers = tuple(value.set_number for value in item.sets)
    if numbers != tuple(range(1, len(item.sets) + 1)):
        raise WorkoutRepositoryError("STRENGTH_SET_ORDER_INVALID")
    return StrengthExerciseSnapshot(
        catalog_exercise_id=item.catalog_exercise_id,
        exercise_name=definition.name,
        primary_muscle=definition.primary_muscle,
        secondary_muscles=definition.secondary_muscles,
        sets=item.sets,
        provenance=provenance,
        custom_exercise=custom,
    )


def _cardio_snapshot(
    connection,
    user_id: str,
    item,
    weight: float,
) -> CardioItemSnapshot:
    definition, provenance, custom = _exercise(
        connection,
        user_id,
        item.catalog_exercise_id,
        item.custom_exercise,
        required_type="cardio",
    )
    try:
        result = cardio_calories(
            duration_min=item.duration_min,
            device_calories=item.device_calories,
            met=definition.met,
            weight_kg=weight,
        )
    except WorkoutDomainError as error:
        raise WorkoutRepositoryError(error.code) from None
    snapshot_provenance = {
        **provenance,
        "primary_muscle_snapshot": definition.primary_muscle,
        "secondary_muscles_snapshot": list(definition.secondary_muscles),
    }
    return CardioItemSnapshot(
        catalog_exercise_id=item.catalog_exercise_id,
        activity_name=definition.name,
        primary_muscle=definition.primary_muscle,
        secondary_muscles=definition.secondary_muscles,
        duration_min=item.duration_min,
        device_calories=item.device_calories,
        met=definition.met,
        estimated_calories=result.calories,
        is_estimate=result.is_estimate,
        estimate=asdict(result),
        provenance=snapshot_provenance,
        custom_exercise=custom,
    )


def _exercise(
    connection,
    user_id: str,
    catalog_id: str | None,
    custom: CustomExerciseSnapshot | None,
    *,
    required_type: str,
):
    if (catalog_id is None) == (custom is None):
        raise WorkoutRepositoryError("EXERCISE_SOURCE_INVALID")
    if catalog_id is not None:
        row = connection.execute(
            """
            SELECT * FROM exercise_catalog
            WHERE id = ? AND active = 1
              AND (owner_user_id IS NULL OR owner_user_id = ?)
            """,
            (catalog_id, user_id),
        ).fetchone()
        if row is None:
            raise WorkoutRepositoryError("EXERCISE_NOT_VISIBLE")
        definition = CustomExerciseSnapshot(
            name=row["name"],
            exercise_type=row["exercise_type"],
            primary_muscle=row["primary_muscle"],
            secondary_muscles=tuple(
                json.loads(row["secondary_muscles_json"])
            ),
            met=row["met"],
        )
        provenance = {
            "source_name": row["source_name"],
            "source_record_id": row["source_record_id"],
            "dataset_version": row["dataset_version"],
            "license": row["license"],
            "attribution": row["attribution"],
            **json.loads(row["provenance_json"]),
        }
        custom_snapshot = None
    else:
        definition = _validated_custom(custom)
        provenance = {"entry_method": "form"}
        custom_snapshot = definition
    if definition.exercise_type != required_type:
        raise WorkoutRepositoryError("EXERCISE_TYPE_MISMATCH")
    return definition, provenance, custom_snapshot


def _validated_custom(value: CustomExerciseSnapshot) -> CustomExerciseSnapshot:
    name = _text(value.name, "EXERCISE_NAME_REQUIRED", 100)
    muscle = _text(
        value.primary_muscle,
        "EXERCISE_PRIMARY_MUSCLE_REQUIRED",
        60,
    )
    if value.exercise_type not in {"strength", "cardio"}:
        raise WorkoutRepositoryError("EXERCISE_TYPE_INVALID")
    return CustomExerciseSnapshot(
        name=name,
        exercise_type=value.exercise_type,
        primary_muscle=muscle,
        secondary_muscles=tuple(
            _text(item, "EXERCISE_SECONDARY_MUSCLE_INVALID", 60)
            for item in value.secondary_muscles
        ),
        met=value.met,
    )


def _effective_weight(connection, user_id: str, log_date: str) -> float:
    row = connection.execute(
        """
        SELECT weight_kg FROM user_profile_versions
        WHERE user_id = ? AND substr(effective_from, 1, 10) <= ?
        ORDER BY effective_from DESC, created_at DESC, id DESC
        LIMIT 1
        """,
        (user_id, log_date),
    ).fetchone()
    if row is None:
        raise WorkoutRepositoryError("WORKOUT_PROFILE_REQUIRED")
    return row["weight_kg"]


def _validate_header(payload: WorkoutDraftInput) -> None:
    try:
        date.fromisoformat(payload.log_date)
    except (TypeError, ValueError):
        raise WorkoutRepositoryError("WORKOUT_DATE_INVALID") from None
    _text(payload.title, "WORKOUT_TITLE_REQUIRED", 100)
    if payload.entry_method != "form":
        raise WorkoutRepositoryError("WORKOUT_ENTRY_METHOD_INVALID")
    if payload.duration_min is not None and payload.duration_min <= 0:
        raise WorkoutRepositoryError("WORKOUT_DURATION_INVALID")
    if payload.intensity is not None and payload.intensity not in {
        "low",
        "medium",
        "high",
    }:
        raise WorkoutRepositoryError("WORKOUT_INTENSITY_INVALID")


def _confirmed_exercise_id(
    connection,
    id_factory: IdFactory,
    user_id: str,
    catalog_id: str | None,
    custom: CustomExerciseSnapshot | None,
    now: str,
) -> str:
    if catalog_id is not None:
        return catalog_id
    if custom is None:
        raise WorkoutRepositoryError("EXERCISE_SOURCE_INVALID")
    exercise_id = id_factory()
    connection.execute(
        """
        INSERT INTO exercise_catalog (
            id, owner_user_id, source, source_name, source_record_id, name,
            exercise_type, primary_muscle, secondary_muscles_json, met,
            provenance_json, created_at, updated_at
        ) VALUES (
            ?, ?, 'user_custom', 'user-custom', ?, ?, ?, ?, ?, ?,
            '{"entry_method":"form"}', ?, ?
        )
        """,
        (
            exercise_id,
            user_id,
            exercise_id,
            custom.name,
            custom.exercise_type,
            custom.primary_muscle,
            json.dumps(
                custom.secondary_muscles,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            custom.met,
            now,
            now,
        ),
    )
    _replace_search(
        connection,
        exercise_id=exercise_id,
        name=custom.name,
        aliases=(),
        source_tokens="user custom",
        id_factory=id_factory,
    )
    return exercise_id


def _usage(
    connection,
    id_factory: IdFactory,
    user_id: str,
    exercise_id: str,
    now: str,
) -> None:
    connection.execute(
        """
        INSERT INTO catalog_usage (
            id, user_id, exercise_id, use_count, last_used_at
        ) VALUES (?, ?, ?, 1, ?)
        ON CONFLICT(user_id, exercise_id)
        WHERE exercise_id IS NOT NULL DO UPDATE SET
            use_count = catalog_usage.use_count + 1,
            last_used_at = excluded.last_used_at
        """,
        (id_factory(), user_id, exercise_id, now),
    )


def _ensure_daily_log(
    connection,
    id_factory: IdFactory,
    user_id: str,
    log_date: str,
    now: str,
) -> None:
    connection.execute(
        """
        INSERT INTO daily_logs (
            id, user_id, log_date, planned_meal_count, created_at, updated_at
        ) VALUES (?, ?, ?, 3, ?, ?)
        ON CONFLICT(user_id, log_date) DO NOTHING
        """,
        (id_factory(), user_id, log_date, now, now),
    )


def _load_session(connection, session_id: str) -> ConfirmedWorkout:
    row = connection.execute(
        "SELECT * FROM training_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        raise WorkoutRepositoryError("WORKOUT_NOT_FOUND")
    strength_rows = connection.execute(
        """
        SELECT * FROM strength_exercises
        WHERE session_id = ? ORDER BY position, id
        """,
        (session_id,),
    ).fetchall()
    strength = []
    for item in strength_rows:
        set_rows = connection.execute(
            """
            SELECT * FROM strength_sets
            WHERE strength_exercise_id = ? ORDER BY set_number
            """,
            (item["id"],),
        ).fetchall()
        strength.append(
            StrengthExerciseSnapshot(
                catalog_exercise_id=item["catalog_exercise_id"],
                exercise_name=item["exercise_name"],
                primary_muscle=item["primary_muscle"],
                secondary_muscles=tuple(
                    json.loads(item["secondary_muscles_json"])
                ),
                sets=tuple(
                    StrengthSet(
                        set_number=value["set_number"],
                        reps=value["reps"],
                        load_kg=value["load_kg"],
                        bodyweight=bool(value["bodyweight"]),
                    )
                    for value in set_rows
                ),
                provenance=json.loads(item["provenance_json"]),
            )
        )
    cardio_rows = connection.execute(
        """
        SELECT * FROM cardio_items
        WHERE session_id = ? ORDER BY position, id
        """,
        (session_id,),
    ).fetchall()
    cardio = tuple(
        _cardio_from_row(item) for item in cardio_rows
    )
    estimate = json.loads(row["estimate_json"])
    weight = estimate.pop("weight_kg_snapshot")
    return ConfirmedWorkout(
        id=row["id"],
        user_id=row["user_id"],
        log_date=row["log_date"],
        title=row["title"],
        started_at=row["started_at"],
        duration_min=row["duration_min"],
        intensity=row["intensity"],
        entry_method=row["entry_method"],
        weight_kg_snapshot=weight,
        estimated_calories=row["estimated_calories"],
        estimate=estimate,
        strength_exercises=tuple(strength),
        cardio_items=cardio,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _cardio_from_row(row) -> CardioItemSnapshot:
    estimate = json.loads(row["estimate_json"])
    is_estimate = bool(estimate.pop("is_estimate"))
    provenance = json.loads(row["provenance_json"])
    return CardioItemSnapshot(
        catalog_exercise_id=row["catalog_exercise_id"],
        activity_name=row["activity_name"],
        primary_muscle=provenance.get(
            "primary_muscle_snapshot",
            "cardiovascular",
        ),
        secondary_muscles=tuple(
            provenance.get("secondary_muscles_snapshot", ())
        ),
        duration_min=row["duration_min"],
        device_calories=row["device_calories"],
        met=row["met"],
        estimated_calories=row["estimated_calories"],
        is_estimate=is_estimate,
        estimate=estimate,
        provenance=provenance,
    )


def _payload_json(payload: WorkoutDraftPayload) -> str:
    return json.dumps(
        asdict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _draft(row) -> WorkoutDraft:
    raw = json.loads(row["payload_json"])
    return WorkoutDraft(
        id=row["id"],
        user_id=row["user_id"],
        payload=_payload(raw),
        version=row["version"],
        expires_at=row["expires_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _payload(raw: dict[str, object]) -> WorkoutDraftPayload:
    strength = tuple(
        StrengthExerciseSnapshot(
            catalog_exercise_id=item["catalog_exercise_id"],
            exercise_name=item["exercise_name"],
            primary_muscle=item["primary_muscle"],
            secondary_muscles=tuple(item["secondary_muscles"]),
            sets=tuple(StrengthSet(**value) for value in item["sets"]),
            provenance=item["provenance"],
            custom_exercise=(
                CustomExerciseSnapshot(**item["custom_exercise"])
                if item["custom_exercise"] is not None
                else None
            ),
        )
        for item in raw["strength_exercises"]
    )
    cardio = tuple(
        CardioItemSnapshot(
            catalog_exercise_id=item["catalog_exercise_id"],
            activity_name=item["activity_name"],
            primary_muscle=item["primary_muscle"],
            secondary_muscles=tuple(item["secondary_muscles"]),
            duration_min=item["duration_min"],
            device_calories=item["device_calories"],
            met=item["met"],
            estimated_calories=item["estimated_calories"],
            is_estimate=item["is_estimate"],
            estimate=item["estimate"],
            provenance=item["provenance"],
            custom_exercise=(
                CustomExerciseSnapshot(**item["custom_exercise"])
                if item["custom_exercise"] is not None
                else None
            ),
        )
        for item in raw["cardio_items"]
    )
    return WorkoutDraftPayload(
        log_date=raw["log_date"],
        title=raw["title"],
        started_at=raw["started_at"],
        duration_min=raw["duration_min"],
        intensity=raw["intensity"],
        entry_method="form",
        weight_kg_snapshot=raw["weight_kg_snapshot"],
        estimated_calories=raw["estimated_calories"],
        estimate=raw["estimate"],
        strength_exercises=strength,
        cardio_items=cardio,
    )


def _replay(response_json: str, fingerprint: str) -> ConfirmedWorkout:
    saved = json.loads(response_json)
    if saved.get("request_fingerprint") != fingerprint:
        raise WorkoutRepositoryError("IDEMPOTENCY_KEY_REUSED")
    raw = saved["response"]
    payload = _payload(
        {
            **raw,
            "strength_exercises": raw["strength_exercises"],
            "cardio_items": raw["cardio_items"],
        }
    )
    return ConfirmedWorkout(
        id=raw["id"],
        user_id=raw["user_id"],
        log_date=raw["log_date"],
        title=raw["title"],
        started_at=raw["started_at"],
        duration_min=raw["duration_min"],
        intensity=raw["intensity"],
        entry_method=raw["entry_method"],
        weight_kg_snapshot=payload.weight_kg_snapshot,
        estimated_calories=payload.estimated_calories,
        estimate=payload.estimate,
        strength_exercises=payload.strength_exercises,
        cardio_items=payload.cardio_items,
        created_at=raw["created_at"],
        updated_at=raw["updated_at"],
        replayed=True,
    )


def _require_draft(
    connection,
    user_id: str,
    draft_id: str,
    expected_version: int | None,
    now: datetime,
):
    row = connection.execute(
        "SELECT * FROM record_drafts WHERE id = ?",
        (draft_id,),
    ).fetchone()
    if row is None or row["user_id"] != user_id or row["kind"] != "workout":
        raise WorkoutRepositoryError("DRAFT_NOT_FOUND")
    if _expired(row["expires_at"], now):
        raise WorkoutRepositoryError("DRAFT_EXPIRED")
    if expected_version is not None and row["version"] != expected_version:
        raise WorkoutRepositoryError("DRAFT_VERSION_CONFLICT")
    return row


def _future_expiry(value: str, now: datetime) -> str:
    parsed = _parse_time(value, "DRAFT_EXPIRY_INVALID")
    if parsed <= now.astimezone(timezone.utc):
        raise WorkoutRepositoryError("DRAFT_EXPIRY_INVALID")
    return _timestamp(parsed)


def _expired(value: str, now: datetime) -> bool:
    return _parse_time(value, "DRAFT_EXPIRY_INVALID") <= now.astimezone(
        timezone.utc
    )


def _parse_time(value: str, code: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise WorkoutRepositoryError(code) from None
    if parsed.tzinfo is None:
        raise WorkoutRepositoryError(code)
    return parsed.astimezone(timezone.utc)


def _text(value: object, code: str, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkoutRepositoryError(code)
    normalized = unicodedata.normalize("NFKC", value).strip()
    if len(normalized) > max_length:
        raise WorkoutRepositoryError(code)
    return normalized


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00",
        "Z",
    )
