from __future__ import annotations

import json
import sqlite3
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import date, datetime, timezone
from uuid import uuid4

from backend.application.ports.meal_repository import (
    ConfirmedMeal,
    CustomFoodSnapshot,
    MealDraft,
    MealDraftInput,
    MealDraftPayload,
    MealItemSnapshot,
    MealRepositoryError,
)
from backend.domain.meals import (
    FoodDefinition,
    MealDomainError,
    portion_from_food,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase
from backend.infrastructure.repositories.sqlite_daily_log import (
    ensure_daily_log,
)
from backend.infrastructure.repositories.sqlite_food_catalog_repository import (
    _source_tokens,
)


Clock = Callable[[], datetime]
IdFactory = Callable[[], str]
_CONFIRM_OPERATION = "meal_draft_confirm"
_MEAL_TYPES = {"breakfast", "lunch", "dinner", "snack", "custom"}


class SQLiteMealRepository:
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
        payload: MealDraftInput,
        expires_at: str,
    ) -> MealDraft:
        draft_id = self._id_factory()
        with self.database.transaction() as connection:
            now_value = self._clock()
            now = _utc_timestamp(now_value)
            canonical_expiry = _normalize_future_expiry(expires_at, now_value)
            resolved = _resolve_payload(connection, user_id, payload)
            connection.execute(
                """
                INSERT INTO record_drafts (
                    id, user_id, kind, schema_version, payload_json, version,
                    agent_status, expires_at, created_at, updated_at
                ) VALUES (
                    ?, ?, 'meal', 1, ?, 1, 'not_requested', ?, ?, ?
                )
                """,
                (
                    draft_id,
                    user_id,
                    _payload_json(resolved),
                    canonical_expiry,
                    now,
                    now,
                ),
            )
        return MealDraft(
            id=draft_id,
            user_id=user_id,
            payload=resolved,
            version=1,
            expires_at=canonical_expiry,
            created_at=now,
            updated_at=now,
        )

    def get_draft(self, user_id: str, draft_id: str) -> MealDraft | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM record_drafts
                WHERE id = ? AND user_id = ? AND kind = 'meal'
                """,
                (draft_id, user_id),
            ).fetchone()
        if row is None or _is_expired(row["expires_at"], self._clock()):
            return None
        return _draft_from_row(row)

    def update_draft(
        self,
        user_id: str,
        draft_id: str,
        *,
        expected_version: int,
        payload: MealDraftInput,
    ) -> MealDraft:
        with self.database.transaction() as connection:
            now_value = self._clock()
            now = _utc_timestamp(now_value)
            _require_draft_state(
                connection,
                user_id,
                draft_id,
                expected_version=expected_version,
                now=now_value,
            )
            resolved = _resolve_payload(connection, user_id, payload)
            cursor = connection.execute(
                """
                UPDATE record_drafts
                SET payload_json = ?, version = version + 1, updated_at = ?
                WHERE id = ? AND user_id = ? AND kind = 'meal'
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
                _raise_draft_write_error(
                    connection,
                    user_id,
                    draft_id,
                    expected_version,
                    now_value,
                )
            row = connection.execute(
                "SELECT * FROM record_drafts WHERE id = ?",
                (draft_id,),
            ).fetchone()
        return _draft_from_row(row)

    def delete_draft(self, user_id: str, draft_id: str) -> None:
        with self.database.transaction() as connection:
            now_value = self._clock()
            _require_draft_state(
                connection,
                user_id,
                draft_id,
                expected_version=None,
                now=now_value,
            )
            connection.execute(
                """
                DELETE FROM record_drafts
                WHERE id = ? AND user_id = ? AND kind = 'meal'
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
        timezone_name: str = "UTC",
    ) -> ConfirmedMeal:
        with self.database.transaction() as connection:
            now_value = self._clock()
            now = _utc_timestamp(now_value)
            existing = connection.execute(
                """
                SELECT response_json
                FROM idempotency_keys
                WHERE user_id = ? AND operation = ? AND idempotency_key = ?
                """,
                (user_id, _CONFIRM_OPERATION, idempotency_key),
            ).fetchone()
            if existing is not None:
                return _replay_confirmation(
                    existing["response_json"],
                    request_fingerprint,
                )

            row = _require_draft_state(
                connection,
                user_id,
                draft_id,
                expected_version=expected_version,
                now=now_value,
            )
            draft = _draft_from_row(row)
            if not draft.payload.items:
                raise MealRepositoryError("DRAFT_INCOMPLETE")

            ensure_daily_log(
                connection,
                self._id_factory,
                user_id,
                draft.payload.log_date,
                now,
                timezone_name,
            )
            position = _next_meal_position(
                connection,
                user_id,
                draft.payload.log_date,
            )
            meal_id = self._id_factory()
            connection.execute(
                """
                INSERT INTO meals (
                    id, user_id, log_date, name, meal_type, position,
                    entry_method, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'form', ?, ?)
                """,
                (
                    meal_id,
                    user_id,
                    draft.payload.log_date,
                    draft.payload.name,
                    draft.payload.meal_type,
                    position,
                    now,
                    now,
                ),
            )
            for item in draft.payload.items:
                catalog_food_id = item.catalog_food_id
                if catalog_food_id is None:
                    if item.custom_food is None:
                        raise MealRepositoryError("DRAFT_INCOMPLETE")
                    catalog_food_id = _insert_custom_food(
                        connection,
                        self._id_factory,
                        user_id,
                        item.custom_food,
                        now,
                    )
                _insert_meal_item(
                    connection,
                    self._id_factory(),
                    meal_id,
                    catalog_food_id,
                    item,
                    now,
                )
                _record_food_usage(
                    connection,
                    self._id_factory,
                    user_id,
                    catalog_food_id,
                    now,
                )

            connection.execute(
                """
                UPDATE daily_logs
                SET planned_meal_count = MAX(
                        planned_meal_count,
                        (
                            SELECT COUNT(*)
                            FROM meals
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

            confirmed = _load_meal(connection, meal_id)
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
                WHERE id = ? AND user_id = ? AND kind = 'meal'
                """,
                (draft_id, user_id),
            )
        return confirmed

    def list_meals(
        self,
        user_id: str,
        log_date: str,
    ) -> tuple[ConfirmedMeal, ...]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT id
                FROM meals
                WHERE user_id = ? AND log_date = ?
                ORDER BY position, id
                """,
                (user_id, log_date),
            ).fetchall()
            return tuple(_load_meal(connection, row["id"]) for row in rows)


def _resolve_payload(
    connection: sqlite3.Connection,
    user_id: str,
    payload: MealDraftInput,
) -> MealDraftPayload:
    _validate_meal_header(payload)
    try:
        items = tuple(
            _resolve_item(connection, user_id, item)
            for item in payload.items
        )
    except MealDomainError as error:
        raise MealRepositoryError(error.code) from None
    return MealDraftPayload(
        log_date=payload.log_date,
        name=payload.name.strip(),
        meal_type=payload.meal_type,
        entry_method="form",
        items=items,
    )


def _resolve_item(
    connection: sqlite3.Connection,
    user_id: str,
    item,
) -> MealItemSnapshot:
    if (item.catalog_food_id is None) == (item.custom_food is None):
        raise MealRepositoryError("MEAL_ITEM_SOURCE_INVALID")
    if item.catalog_food_id is not None:
        row = connection.execute(
            """
            SELECT *
            FROM food_catalog
            WHERE id = ? AND active = 1
              AND (owner_user_id IS NULL OR owner_user_id = ?)
            """,
            (item.catalog_food_id, user_id),
        ).fetchone()
        if row is None:
            raise MealRepositoryError("FOOD_NOT_VISIBLE")
        definition = FoodDefinition(
            name=row["name"],
            basis_type=row["basis_type"],
            basis_amount=row["basis_amount"],
            unit=row["unit"],
            calories=row["calories"],
            carbs=row["carbs"],
            protein=row["protein"],
            fat=row["fat"],
            source=row["source"],
        )
        custom_food = None
        provenance = {
            "source_name": row["source_name"],
            "source_record_id": row["source_record_id"],
            "dataset_version": row["dataset_version"],
            "license": row["license"],
            "attribution": row["attribution"],
            **json.loads(row["provenance_json"]),
        }
    else:
        custom_food = CustomFoodSnapshot(
            name=_normalize_text(item.custom_food.name),
            basis_type=item.custom_food.basis_type,
            basis_amount=item.custom_food.basis_amount,
            unit=_normalize_text(item.custom_food.unit),
            calories=item.custom_food.calories,
            carbs=item.custom_food.carbs,
            protein=item.custom_food.protein,
            fat=item.custom_food.fat,
        )
        definition = FoodDefinition(
            name=custom_food.name,
            basis_type=custom_food.basis_type,
            basis_amount=custom_food.basis_amount,
            unit=custom_food.unit,
            calories=custom_food.calories,
            carbs=custom_food.carbs,
            protein=custom_food.protein,
            fat=custom_food.fat,
            source="user_custom",
        )
        provenance = {"entry_method": "form"}
    try:
        portion = portion_from_food(
            definition,
            amount=item.amount,
            unit=item.unit,
        )
    except MealDomainError as error:
        raise MealRepositoryError(error.code) from None
    return MealItemSnapshot(
        catalog_food_id=item.catalog_food_id,
        food_name=portion.food_name,
        amount=portion.amount,
        unit=portion.unit,
        basis_type=portion.basis_type,
        calories=portion.calories,
        carbs=portion.carbs,
        protein=portion.protein,
        fat=portion.fat,
        source=portion.source,
        is_estimate=False,
        uncertainty={},
        assumptions=(),
        provenance=provenance,
        custom_food=custom_food,
    )


def _validate_meal_header(payload: MealDraftInput) -> None:
    try:
        date.fromisoformat(payload.log_date)
    except (TypeError, ValueError):
        raise MealRepositoryError("MEAL_DATE_INVALID") from None
    if not isinstance(payload.name, str) or not payload.name.strip():
        raise MealRepositoryError("MEAL_NAME_REQUIRED")
    if len(payload.name.strip()) > 100:
        raise MealRepositoryError("MEAL_NAME_TOO_LONG")
    if payload.meal_type not in _MEAL_TYPES:
        raise MealRepositoryError("MEAL_TYPE_INVALID")
    if payload.entry_method != "form":
        raise MealRepositoryError("MEAL_ENTRY_METHOD_INVALID")


def _next_meal_position(
    connection: sqlite3.Connection,
    user_id: str,
    log_date: str,
) -> int:
    row = connection.execute(
        """
        SELECT COALESCE(MAX(position), 0) + 1 AS next_position
        FROM meals
        WHERE user_id = ? AND log_date = ?
        """,
        (user_id, log_date),
    ).fetchone()
    return row["next_position"]


def _insert_custom_food(
    connection: sqlite3.Connection,
    id_factory: IdFactory,
    user_id: str,
    food: CustomFoodSnapshot,
    now: str,
) -> str:
    food_id = id_factory()
    connection.execute(
        """
        INSERT INTO food_catalog (
            id, owner_user_id, source, source_name, source_record_id, name,
            basis_type, basis_amount, unit, calories, carbs, protein, fat,
            provenance_json, created_at, updated_at
        ) VALUES (
            ?, ?, 'user_custom', 'user-custom', ?, ?, ?, ?, ?, ?, ?, ?, ?,
            '{"entry_method":"form"}', ?, ?
        )
        """,
        (
            food_id,
            user_id,
            food_id,
            food.name,
            food.basis_type,
            food.basis_amount,
            food.unit,
            food.calories,
            food.carbs,
            food.protein,
            food.fat,
            now,
            now,
        ),
    )
    connection.execute(
        """
        INSERT INTO catalog_search (
            catalog_kind, catalog_id, name, aliases, pinyin, source_tokens
        ) VALUES ('food', ?, ?, '', '', ?)
        """,
        (food_id, food.name, _source_tokens(food.name, (), "user custom")),
    )
    return food_id


def _insert_meal_item(
    connection: sqlite3.Connection,
    item_id: str,
    meal_id: str,
    catalog_food_id: str,
    item: MealItemSnapshot,
    now: str,
) -> None:
    connection.execute(
        """
        INSERT INTO meal_items (
            id, meal_id, catalog_food_id, food_name, amount, unit,
            basis_type, calories, carbs, protein, fat, source, is_estimate,
            uncertainty_json, assumptions_json, provenance_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id,
            meal_id,
            catalog_food_id,
            item.food_name,
            item.amount,
            item.unit,
            item.basis_type,
            item.calories,
            item.carbs,
            item.protein,
            item.fat,
            item.source,
            int(item.is_estimate),
            json.dumps(item.uncertainty, sort_keys=True, separators=(",", ":")),
            json.dumps(item.assumptions, ensure_ascii=False, separators=(",", ":")),
            json.dumps(
                item.provenance,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            now,
        ),
    )


def _record_food_usage(
    connection: sqlite3.Connection,
    id_factory: IdFactory,
    user_id: str,
    food_id: str,
    now: str,
) -> None:
    connection.execute(
        """
        INSERT INTO catalog_usage (
            id, user_id, food_id, use_count, last_used_at
        ) VALUES (?, ?, ?, 1, ?)
        ON CONFLICT(user_id, food_id) WHERE food_id IS NOT NULL
        DO UPDATE SET
            use_count = catalog_usage.use_count + 1,
            last_used_at = excluded.last_used_at
        """,
        (id_factory(), user_id, food_id, now),
    )


def _load_meal(
    connection: sqlite3.Connection,
    meal_id: str,
) -> ConfirmedMeal:
    row = connection.execute(
        "SELECT * FROM meals WHERE id = ?",
        (meal_id,),
    ).fetchone()
    if row is None:
        raise MealRepositoryError("MEAL_NOT_FOUND")
    item_rows = connection.execute(
        """
        SELECT *
        FROM meal_items
        WHERE meal_id = ?
        ORDER BY rowid
        """,
        (meal_id,),
    ).fetchall()
    items = tuple(
        MealItemSnapshot(
            catalog_food_id=item["catalog_food_id"],
            food_name=item["food_name"],
            amount=item["amount"],
            unit=item["unit"],
            basis_type=item["basis_type"],
            calories=item["calories"],
            carbs=item["carbs"],
            protein=item["protein"],
            fat=item["fat"],
            source=item["source"],
            is_estimate=bool(item["is_estimate"]),
            uncertainty=json.loads(item["uncertainty_json"]),
            assumptions=tuple(json.loads(item["assumptions_json"])),
            provenance=json.loads(item["provenance_json"]),
            custom_food=None,
        )
        for item in item_rows
    )
    return ConfirmedMeal(
        id=row["id"],
        user_id=row["user_id"],
        log_date=row["log_date"],
        name=row["name"],
        meal_type=row["meal_type"],
        position=row["position"],
        entry_method=row["entry_method"],
        items=items,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _replay_confirmation(
    response_json: str,
    request_fingerprint: str,
) -> ConfirmedMeal:
    saved = json.loads(response_json)
    if saved.get("request_fingerprint") != request_fingerprint:
        raise MealRepositoryError("IDEMPOTENCY_KEY_REUSED")
    return replace(_meal_from_dict(saved["response"]), replayed=True)


def _meal_from_dict(raw: dict[str, object]) -> ConfirmedMeal:
    items = tuple(
        MealItemSnapshot(
            catalog_food_id=item["catalog_food_id"],
            food_name=item["food_name"],
            amount=item["amount"],
            unit=item["unit"],
            basis_type=item["basis_type"],
            calories=item["calories"],
            carbs=item["carbs"],
            protein=item["protein"],
            fat=item["fat"],
            source=item["source"],
            is_estimate=item["is_estimate"],
            uncertainty=item["uncertainty"],
            assumptions=tuple(item["assumptions"]),
            provenance=item["provenance"],
            custom_food=None,
        )
        for item in raw["items"]
    )
    return ConfirmedMeal(
        id=raw["id"],
        user_id=raw["user_id"],
        log_date=raw["log_date"],
        name=raw["name"],
        meal_type=raw["meal_type"],
        position=raw["position"],
        entry_method=raw["entry_method"],
        items=items,
        created_at=raw["created_at"],
        updated_at=raw["updated_at"],
        replayed=raw.get("replayed", False),
    )


def _payload_json(payload: MealDraftPayload) -> str:
    return json.dumps(
        asdict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _draft_from_row(row: sqlite3.Row) -> MealDraft:
    raw = json.loads(row["payload_json"])
    items = tuple(
        MealItemSnapshot(
            catalog_food_id=item["catalog_food_id"],
            food_name=item["food_name"],
            amount=item["amount"],
            unit=item["unit"],
            basis_type=item["basis_type"],
            calories=item["calories"],
            carbs=item["carbs"],
            protein=item["protein"],
            fat=item["fat"],
            source=item["source"],
            is_estimate=item["is_estimate"],
            uncertainty=item["uncertainty"],
            assumptions=tuple(item["assumptions"]),
            provenance=item["provenance"],
            custom_food=(
                CustomFoodSnapshot(**item["custom_food"])
                if item["custom_food"] is not None
                else None
            ),
        )
        for item in raw["items"]
    )
    return MealDraft(
        id=row["id"],
        user_id=row["user_id"],
        payload=MealDraftPayload(
            log_date=raw["log_date"],
            name=raw["name"],
            meal_type=raw["meal_type"],
            entry_method=raw["entry_method"],
            items=items,
        ),
        version=row["version"],
        expires_at=row["expires_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _raise_draft_write_error(
    connection: sqlite3.Connection,
    user_id: str,
    draft_id: str,
    expected_version: int | None,
    now: datetime,
) -> None:
    _require_draft_state(
        connection,
        user_id,
        draft_id,
        expected_version=expected_version,
        now=now,
    )
    raise MealRepositoryError("DRAFT_UPDATE_FAILED")


def _require_draft_state(
    connection: sqlite3.Connection,
    user_id: str,
    draft_id: str,
    *,
    expected_version: int | None,
    now: datetime,
) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT *
        FROM record_drafts
        WHERE id = ?
        """,
        (draft_id,),
    ).fetchone()
    if row is None or row["user_id"] != user_id or row["kind"] != "meal":
        raise MealRepositoryError("DRAFT_NOT_FOUND")
    if _is_expired(row["expires_at"], now):
        raise MealRepositoryError("DRAFT_EXPIRED")
    if expected_version is not None and row["version"] != expected_version:
        raise MealRepositoryError("DRAFT_VERSION_CONFLICT")
    return row


def _normalize_future_expiry(expires_at: str, now: datetime) -> str:
    parsed = _parse_timestamp(expires_at, "DRAFT_EXPIRY_INVALID")
    normalized_now = now.astimezone(timezone.utc)
    if parsed <= normalized_now:
        raise MealRepositoryError("DRAFT_EXPIRY_INVALID")
    return _utc_timestamp(parsed)


def _is_expired(expires_at: str, now: datetime) -> bool:
    parsed = _parse_timestamp(expires_at, "DRAFT_EXPIRY_INVALID")
    return parsed <= now.astimezone(timezone.utc)


def _parse_timestamp(value: str, code: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise MealRepositoryError(code) from None
    if parsed.tzinfo is None:
        raise MealRepositoryError(code)
    return parsed.astimezone(timezone.utc)


def _normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00",
        "Z",
    )
