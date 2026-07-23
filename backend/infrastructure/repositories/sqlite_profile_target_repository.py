from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid4

from backend.application.ports.profile_target_repository import (
    GoalVersion,
    GoalVersionInput,
    ProfileTargetSetup,
    ProfileTargetRepositoryError,
    ProfileVersion,
    ProfileVersionInput,
    TargetConfirmationState,
    TargetVersion,
    TargetVersionInput,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase


Clock = Callable[[], datetime]
IdFactory = Callable[[], str]
_TARGET_CONFIRM_OPERATION = "profile_target_confirm"


class SQLiteProfileTargetRepository:
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

    def get_setup(self, user_id: str) -> ProfileTargetSetup:
        with self.database.connection() as connection:
            connection.execute("BEGIN")
            try:
                profile_row = connection.execute(
                    """
                    SELECT * FROM user_profile_versions
                    WHERE user_id = ?
                    ORDER BY effective_from DESC, created_at DESC, id DESC
                    LIMIT 1
                    """,
                    (user_id,),
                ).fetchone()
                goal_row = connection.execute(
                    """
                    SELECT * FROM overall_goal_versions
                    WHERE user_id = ?
                    ORDER BY effective_from DESC, created_at DESC, id DESC
                    LIMIT 1
                    """,
                    (user_id,),
                ).fetchone()
                target_row = connection.execute(
                    """
                    SELECT * FROM daily_target_versions
                    WHERE user_id = ?
                    ORDER BY effective_from DESC, created_at DESC, id DESC
                    LIMIT 1
                    """,
                    (user_id,),
                ).fetchone()
            finally:
                connection.rollback()
        return ProfileTargetSetup(
            profile=_profile_from_row(profile_row) if profile_row else None,
            goal=_goal_from_row(goal_row) if goal_row else None,
            target=_target_from_row(target_row) if target_row else None,
        )

    def get_latest_profile(self, user_id: str) -> ProfileVersion | None:
        with self.database.connection() as connection:
            row = _latest_profile_row(connection, user_id)
        return _profile_from_row(row) if row is not None else None

    def get_profile_version(
        self, user_id: str, version_id: str
    ) -> ProfileVersion | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM user_profile_versions
                WHERE user_id = ? AND id = ?
                """,
                (user_id, version_id),
            ).fetchone()
        return _profile_from_row(row) if row is not None else None

    def append_profile(
        self,
        user_id: str,
        profile: ProfileVersionInput,
    ) -> ProfileVersion:
        profile_id = self._id_factory()
        created_at = _utc_timestamp(self._clock())
        with self.database.transaction() as connection:
            _insert_profile(connection, profile_id, user_id, profile, created_at)
        return ProfileVersion(
            **profile.__dict__,
            id=profile_id,
            user_id=user_id,
            created_at=created_at,
        )

    def append_profile_if_changed(
        self,
        user_id: str,
        profile: ProfileVersionInput,
    ) -> ProfileVersion:
        profile_id = self._id_factory()
        created_at = _utc_timestamp(self._clock())
        with self.database.transaction() as connection:
            current_row = _latest_profile_row(connection, user_id)
            if current_row is not None:
                current = _profile_from_row(current_row)
                if _same_profile_content(current, profile):
                    return current
            _insert_profile(connection, profile_id, user_id, profile, created_at)
        return ProfileVersion(
            **profile.__dict__,
            id=profile_id,
            user_id=user_id,
            created_at=created_at,
        )

    def get_latest_goal(self, user_id: str) -> GoalVersion | None:
        with self.database.connection() as connection:
            row = _latest_goal_row(connection, user_id)
        return _goal_from_row(row) if row is not None else None

    def get_goal_version(
        self, user_id: str, version_id: str
    ) -> GoalVersion | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM overall_goal_versions
                WHERE user_id = ? AND id = ?
                """,
                (user_id, version_id),
            ).fetchone()
        return _goal_from_row(row) if row is not None else None

    def append_goal(self, user_id: str, goal: GoalVersionInput) -> GoalVersion:
        goal_id = self._id_factory()
        created_at = _utc_timestamp(self._clock())
        with self.database.transaction() as connection:
            _insert_goal(connection, goal_id, user_id, goal, created_at)
        return GoalVersion(
            **goal.__dict__,
            id=goal_id,
            user_id=user_id,
            created_at=created_at,
        )

    def append_goal_if_changed(
        self,
        user_id: str,
        goal: GoalVersionInput,
    ) -> GoalVersion:
        goal_id = self._id_factory()
        created_at = _utc_timestamp(self._clock())
        with self.database.transaction() as connection:
            current_row = _latest_goal_row(connection, user_id)
            if current_row is not None:
                current = _goal_from_row(current_row)
                if current.goal == goal.goal:
                    return current
            _insert_goal(connection, goal_id, user_id, goal, created_at)
        return GoalVersion(
            **goal.__dict__,
            id=goal_id,
            user_id=user_id,
            created_at=created_at,
        )

    def get_latest_target(self, user_id: str) -> TargetVersion | None:
        targets = self.list_targets(user_id, limit=1)
        return targets[0] if targets else None

    def append_target(
        self,
        user_id: str,
        target: TargetVersionInput,
    ) -> TargetVersion:
        target_id = self._id_factory()
        created_at = _utc_timestamp(self._clock())
        with self.database.transaction() as connection:
            _insert_target(connection, target_id, user_id, target, created_at)
        return _target_version(target_id, user_id, target, created_at)

    def list_targets(
        self,
        user_id: str,
        *,
        limit: int | None = None,
    ) -> tuple[TargetVersion, ...]:
        sql = """
            SELECT * FROM daily_target_versions
            WHERE user_id = ?
            ORDER BY effective_from DESC, created_at DESC, id DESC
        """
        parameters: tuple[object, ...] = (user_id,)
        if limit is not None:
            sql += " LIMIT ?"
            parameters += (limit,)
        with self.database.connection() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return tuple(_target_from_row(row) for row in rows)

    def bootstrap(
        self,
        user_id: str,
        profile: ProfileVersionInput,
        goal: GoalVersionInput,
    ) -> ProfileTargetSetup:
        profile_id = self._id_factory()
        goal_id = self._id_factory()
        created_at = _utc_timestamp(self._clock())
        with self.database.transaction() as connection:
            _insert_profile(connection, profile_id, user_id, profile, created_at)
            _insert_goal(connection, goal_id, user_id, goal, created_at)
        return ProfileTargetSetup(
            profile=ProfileVersion(
                **profile.__dict__,
                id=profile_id,
                user_id=user_id,
                created_at=created_at,
            ),
            goal=GoalVersion(
                **goal.__dict__,
                id=goal_id,
                user_id=user_id,
                created_at=created_at,
            ),
            target=None,
        )

    def confirm_target_once(
        self,
        user_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        target: TargetVersionInput,
    ) -> TargetVersion:
        return self.confirm_target(
            user_id,
            idempotency_key,
            request_fingerprint,
            target,
        ).target

    def confirm_target(
        self,
        user_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        target: TargetVersionInput,
    ) -> TargetConfirmationState:
        target_id = self._id_factory()
        created_at = _utc_timestamp(self._clock())
        with self.database.transaction() as connection:
            existing = connection.execute(
                """
                SELECT response_json FROM idempotency_keys
                WHERE user_id = ? AND operation = ? AND idempotency_key = ?
                """,
                (user_id, _TARGET_CONFIRM_OPERATION, idempotency_key),
            ).fetchone()
            if existing is not None:
                return _replay_confirmation(
                    existing["response_json"], request_fingerprint
                )

            latest_profile = _latest_profile_row(connection, user_id)
            latest_goal = _latest_goal_row(connection, user_id)
            if (
                target.profile_version_id is None
                or target.overall_goal_version_id is None
                or latest_profile is None
                or latest_goal is None
                or latest_profile["id"] != target.profile_version_id
                or latest_goal["id"] != target.overall_goal_version_id
            ):
                raise ProfileTargetRepositoryError("TARGET_PREVIEW_STALE")

            _insert_target(connection, target_id, user_id, target, created_at)
            confirmed = _target_version(target_id, user_id, target, created_at)
            response = {
                "request_fingerprint": request_fingerprint,
                "response": asdict(confirmed),
                "projection_completed": False,
            }
            connection.execute(
                """
                INSERT INTO idempotency_keys (
                    user_id, operation, idempotency_key, response_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    _TARGET_CONFIRM_OPERATION,
                    idempotency_key,
                    json.dumps(response, sort_keys=True, separators=(",", ":")),
                    created_at,
                ),
            )
        return TargetConfirmationState(
            target=confirmed,
            replayed=False,
            projection_completed=False,
        )

    def get_confirmation(
        self,
        user_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> TargetConfirmationState | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT response_json FROM idempotency_keys
                WHERE user_id = ? AND operation = ? AND idempotency_key = ?
                """,
                (user_id, _TARGET_CONFIRM_OPERATION, idempotency_key),
            ).fetchone()
        if row is None:
            return None
        return _replay_confirmation(row["response_json"], request_fingerprint)

    def mark_projection_complete(
        self,
        user_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> TargetConfirmationState:
        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT response_json FROM idempotency_keys
                WHERE user_id = ? AND operation = ? AND idempotency_key = ?
                """,
                (user_id, _TARGET_CONFIRM_OPERATION, idempotency_key),
            ).fetchone()
            if row is None:
                raise ProfileTargetRepositoryError("IDEMPOTENCY_RESULT_NOT_FOUND")
            state = _replay_confirmation(row["response_json"], request_fingerprint)
            if state.projection_completed:
                return state
            stored = json.loads(row["response_json"])
            stored["projection_completed"] = True
            connection.execute(
                """
                UPDATE idempotency_keys SET response_json = ?
                WHERE user_id = ? AND operation = ? AND idempotency_key = ?
                """,
                (
                    json.dumps(stored, sort_keys=True, separators=(",", ":")),
                    user_id,
                    _TARGET_CONFIRM_OPERATION,
                    idempotency_key,
                ),
            )
        return TargetConfirmationState(
            target=state.target,
            replayed=True,
            projection_completed=True,
        )

    def delete_user_data(self, user_id: str) -> None:
        with self.database.transaction() as connection:
            for statement in (
                "DELETE FROM meals WHERE user_id = ?",
                "DELETE FROM training_sessions WHERE user_id = ?",
                "DELETE FROM catalog_favorites WHERE user_id = ?",
                "DELETE FROM catalog_usage WHERE user_id = ?",
                "DELETE FROM record_drafts WHERE user_id = ?",
                "DELETE FROM daily_logs WHERE user_id = ?",
                "DELETE FROM idempotency_keys WHERE user_id = ?",
                "DELETE FROM daily_target_versions WHERE user_id = ?",
                "DELETE FROM user_profile_versions WHERE user_id = ?",
                "DELETE FROM overall_goal_versions WHERE user_id = ?",
            ):
                connection.execute(statement, (user_id,))
            connection.execute(
                """
                DELETE FROM catalog_search
                WHERE (
                    catalog_kind = 'food'
                    AND catalog_id IN (
                        SELECT id FROM food_catalog WHERE owner_user_id = ?
                    )
                ) OR (
                    catalog_kind = 'exercise'
                    AND catalog_id IN (
                        SELECT id FROM exercise_catalog WHERE owner_user_id = ?
                    )
                )
                """,
                (user_id, user_id),
            )
            connection.execute(
                "DELETE FROM food_catalog WHERE owner_user_id = ?",
                (user_id,),
            )
            connection.execute(
                "DELETE FROM exercise_catalog WHERE owner_user_id = ?",
                (user_id,),
            )


def _profile_from_row(row) -> ProfileVersion:
    return ProfileVersion(
        id=row["id"],
        user_id=row["user_id"],
        age=row["age"],
        height_cm=row["height_cm"],
        weight_kg=row["weight_kg"],
        energy_parameter=row["energy_parameter"],
        activity_level=row["activity_level"],
        auto_target_disabled=bool(row["auto_target_disabled"]),
        safety_conditions=tuple(json.loads(row["safety_conditions_json"])),
        effective_from=row["effective_from"],
        created_at=row["created_at"],
    )


def _goal_from_row(row) -> GoalVersion:
    return GoalVersion(
        id=row["id"],
        user_id=row["user_id"],
        goal=row["goal"],
        effective_from=row["effective_from"],
        created_at=row["created_at"],
    )


def _insert_profile(
    connection,
    profile_id: str,
    user_id: str,
    profile: ProfileVersionInput,
    created_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO user_profile_versions (
            id, user_id, age, height_cm, weight_kg, energy_parameter,
            activity_level, auto_target_disabled,
            safety_conditions_json, effective_from, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            profile_id,
            user_id,
            profile.age,
            profile.height_cm,
            profile.weight_kg,
            profile.energy_parameter,
            profile.activity_level,
            int(profile.auto_target_disabled),
            json.dumps(profile.safety_conditions),
            profile.effective_from,
            created_at,
        ),
    )


def _insert_goal(
    connection,
    goal_id: str,
    user_id: str,
    goal: GoalVersionInput,
    created_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO overall_goal_versions (
            id, user_id, goal, effective_from, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (goal_id, user_id, goal.goal, goal.effective_from, created_at),
    )


def _insert_target(
    connection,
    target_id: str,
    user_id: str,
    target: TargetVersionInput,
    created_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO daily_target_versions (
            id, user_id, profile_version_id, overall_goal_version_id,
            calories, carbs, protein, fat, source, formula_version,
            rationale_json, effective_from, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            target_id,
            user_id,
            target.profile_version_id,
            target.overall_goal_version_id,
            target.calories,
            target.carbs,
            target.protein,
            target.fat,
            target.source,
            target.formula_version,
            json.dumps(target.rationale, sort_keys=True, separators=(",", ":")),
            target.effective_from,
            created_at,
        ),
    )


def _target_version(
    target_id: str,
    user_id: str,
    target: TargetVersionInput,
    created_at: str,
) -> TargetVersion:
    return TargetVersion(
        **target.__dict__,
        id=target_id,
        user_id=user_id,
        created_at=created_at,
    )


def _target_from_row(row) -> TargetVersion:
    return TargetVersion(
        id=row["id"],
        user_id=row["user_id"],
        profile_version_id=row["profile_version_id"],
        overall_goal_version_id=row["overall_goal_version_id"],
        calories=row["calories"],
        carbs=row["carbs"],
        protein=row["protein"],
        fat=row["fat"],
        source=row["source"],
        formula_version=row["formula_version"],
        rationale=json.loads(row["rationale_json"]),
        effective_from=row["effective_from"],
        created_at=row["created_at"],
    )


def _replay_confirmation(
    response_json: str,
    request_fingerprint: str,
) -> TargetConfirmationState:
    stored = json.loads(response_json)
    if stored.get("request_fingerprint") != request_fingerprint:
        raise ProfileTargetRepositoryError("IDEMPOTENCY_KEY_REUSED")
    response = stored["response"]
    return TargetConfirmationState(
        target=TargetVersion(**response),
        replayed=True,
        projection_completed=bool(stored.get("projection_completed", False)),
    )


def _latest_profile_row(connection, user_id: str):
    return connection.execute(
        """
        SELECT * FROM user_profile_versions
        WHERE user_id = ?
        ORDER BY effective_from DESC, created_at DESC, id DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()


def _latest_goal_row(connection, user_id: str):
    return connection.execute(
        """
        SELECT * FROM overall_goal_versions
        WHERE user_id = ?
        ORDER BY effective_from DESC, created_at DESC, id DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()


def _same_profile_content(
    current: ProfileVersion,
    update: ProfileVersionInput,
) -> bool:
    return all(
        getattr(current, field) == getattr(update, field)
        for field in (
            "age",
            "height_cm",
            "weight_kg",
            "energy_parameter",
            "activity_level",
            "auto_target_disabled",
            "safety_conditions",
        )
    )


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
