from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from backend.application.ports.exercise_catalog_repository import (
    ExerciseCatalogItem,
    ExerciseCatalogRepositoryError,
    NewCustomExercise,
)
from backend.infrastructure.repositories.sqlite_food_catalog_repository import (
    _fts_query,
    _source_tokens,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase


Clock = Callable[[], datetime]
IdFactory = Callable[[], str]
_SELECT = """
    SELECT
        exercise.*,
        COALESCE(favorite.is_favorite, 0) AS is_favorite,
        COALESCE(usage.use_count, 0) AS use_count,
        usage.last_used_at,
        CASE
            WHEN usage.exercise_id IS NOT NULL THEN 0
            WHEN favorite.exercise_id IS NOT NULL THEN 1
            WHEN exercise.owner_user_id IS NOT NULL THEN 2
            ELSE 3
        END AS rank_group,
        COALESCE((
            SELECT group_concat(ordered_alias.alias, char(31))
            FROM (
                SELECT alias
                FROM catalog_aliases
                WHERE exercise_id = exercise.id
                ORDER BY rowid
            ) AS ordered_alias
        ), '') AS stored_aliases
    FROM exercise_catalog AS exercise
    LEFT JOIN (
        SELECT exercise_id, 1 AS is_favorite
        FROM catalog_favorites
        WHERE user_id = ? AND exercise_id IS NOT NULL
    ) AS favorite ON favorite.exercise_id = exercise.id
    LEFT JOIN (
        SELECT exercise_id, use_count, last_used_at
        FROM catalog_usage
        WHERE user_id = ? AND exercise_id IS NOT NULL
    ) AS usage ON usage.exercise_id = exercise.id
"""
_VISIBLE = """
    exercise.active = 1
    AND (exercise.owner_user_id IS NULL OR exercise.owner_user_id = ?)
"""
_ORDER_BY = """
    ORDER BY rank_group,
        CASE WHEN usage.exercise_id IS NOT NULL THEN usage.last_used_at END DESC,
        usage.use_count DESC,
        lower(exercise.name), exercise.name, exercise.id
"""
_ORDER = f"{_ORDER_BY} LIMIT ?"


class SQLiteExerciseCatalogRepository:
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

    def search(
        self,
        user_id: str,
        query: str,
        *,
        limit: int,
    ) -> tuple[ExerciseCatalogItem, ...]:
        match = _fts_query(query)
        with self.database.connection() as connection:
            if match:
                rows = connection.execute(
                    f"""
                    {_SELECT}
                    WHERE {_VISIBLE}
                      AND exercise.id IN (
                          SELECT catalog_id FROM catalog_search
                          WHERE catalog_kind = 'exercise'
                            AND catalog_search MATCH ?
                      )
                    {_ORDER_BY}
                    """,
                    (
                        user_id,
                        user_id,
                        user_id,
                        match,
                    ),
                ).fetchall()
                rows = sorted(rows, key=lambda row: _exact_match_rank(row, query))
                rows = rows[:limit]
            else:
                rows = connection.execute(
                    f"{_SELECT} WHERE {_VISIBLE} {_ORDER}",
                    (user_id, user_id, user_id, limit),
                ).fetchall()
        return tuple(_item(row) for row in rows)

    def create_custom_exercise(
        self,
        user_id: str,
        exercise: NewCustomExercise,
    ) -> ExerciseCatalogItem:
        definition = exercise.definition
        if definition.source != "user_custom":
            raise ExerciseCatalogRepositoryError(
                "CUSTOM_EXERCISE_SOURCE_INVALID"
            )
        exercise_id = self._id_factory()
        aliases = _aliases(exercise.aliases)
        now = _timestamp(self._clock())
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO exercise_catalog (
                    id, owner_user_id, source, source_name, source_record_id,
                    name, exercise_type, primary_muscle,
                    secondary_muscles_json, met, provenance_json,
                    created_at, updated_at
                ) VALUES (
                    ?, ?, 'user_custom', 'user-custom', ?, ?, ?, ?, ?, ?,
                    '{"entry_method":"form"}', ?, ?
                )
                """,
                (
                    exercise_id,
                    user_id,
                    exercise_id,
                    definition.name.strip(),
                    definition.exercise_type,
                    definition.primary_muscle.strip(),
                    json.dumps(
                        definition.secondary_muscles,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    definition.met,
                    now,
                    now,
                ),
            )
            _replace_search(
                connection,
                exercise_id=exercise_id,
                name=definition.name.strip(),
                aliases=aliases,
                source_tokens="user custom",
                id_factory=self._id_factory,
            )
        created = self._get(user_id, exercise_id)
        if created is None:
            raise ExerciseCatalogRepositoryError(
                "CUSTOM_EXERCISE_CREATE_FAILED"
            )
        return created

    def set_favorite(
        self,
        user_id: str,
        exercise_id: str,
        favorite: bool,
    ) -> None:
        with self.database.transaction() as connection:
            _require_visible(connection, user_id, exercise_id)
            if favorite:
                connection.execute(
                    """
                    INSERT INTO catalog_favorites (id, user_id, exercise_id)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, exercise_id)
                    WHERE exercise_id IS NOT NULL DO NOTHING
                    """,
                    (self._id_factory(), user_id, exercise_id),
                )
            else:
                connection.execute(
                    """
                    DELETE FROM catalog_favorites
                    WHERE user_id = ? AND exercise_id = ?
                    """,
                    (user_id, exercise_id),
                )

    def record_usage(self, user_id: str, exercise_id: str) -> None:
        now = _timestamp(self._clock())
        with self.database.transaction() as connection:
            _require_visible(connection, user_id, exercise_id)
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
                (self._id_factory(), user_id, exercise_id, now),
            )

    def _get(
        self,
        user_id: str,
        exercise_id: str,
    ) -> ExerciseCatalogItem | None:
        with self.database.connection() as connection:
            row = connection.execute(
                f"{_SELECT} WHERE {_VISIBLE} AND exercise.id = ?",
                (user_id, user_id, user_id, exercise_id),
            ).fetchone()
        return _item(row) if row is not None else None


def _aliases(values: tuple[str, ...]) -> tuple[str, ...]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ExerciseCatalogRepositoryError("EXERCISE_ALIAS_INVALID")
        alias = unicodedata.normalize("NFKC", value).strip()
        identity = alias.casefold()
        if alias and identity not in seen:
            seen.add(identity)
            output.append(alias)
    return tuple(output)


def _replace_search(
    connection: sqlite3.Connection,
    *,
    exercise_id: str,
    name: str,
    aliases: tuple[str, ...],
    source_tokens: str,
    id_factory: IdFactory,
) -> None:
    connection.execute(
        "DELETE FROM catalog_aliases WHERE exercise_id = ?",
        (exercise_id,),
    )
    connection.execute(
        """
        DELETE FROM catalog_search
        WHERE catalog_kind = 'exercise' AND catalog_id = ?
        """,
        (exercise_id,),
    )
    for alias in aliases:
        connection.execute(
            """
            INSERT INTO catalog_aliases (
                id, exercise_id, alias, normalized_alias, alias_kind
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                id_factory(),
                exercise_id,
                alias,
                alias.casefold(),
                "zh" if re.search(r"[\u3400-\u9fff]", alias) else "alias",
            ),
        )
    connection.execute(
        """
        INSERT INTO catalog_search (
            catalog_kind, catalog_id, name, aliases, pinyin, source_tokens
        ) VALUES ('exercise', ?, ?, ?, '', ?)
        """,
        (
            exercise_id,
            name,
            " ".join(aliases),
            _source_tokens(name, aliases, source_tokens),
        ),
    )


def _require_visible(
    connection: sqlite3.Connection,
    user_id: str,
    exercise_id: str,
) -> None:
    row = connection.execute(
        """
        SELECT 1 FROM exercise_catalog
        WHERE id = ? AND active = 1
          AND (owner_user_id IS NULL OR owner_user_id = ?)
        """,
        (exercise_id, user_id),
    ).fetchone()
    if row is None:
        raise ExerciseCatalogRepositoryError("EXERCISE_NOT_VISIBLE")


def _item(row: sqlite3.Row) -> ExerciseCatalogItem:
    return ExerciseCatalogItem(
        id=row["id"],
        owner_user_id=row["owner_user_id"],
        source=row["source"],
        source_name=row["source_name"],
        source_record_id=row["source_record_id"],
        dataset_version=row["dataset_version"],
        name=row["name"],
        exercise_type=row["exercise_type"],
        primary_muscle=row["primary_muscle"],
        secondary_muscles=tuple(
            json.loads(row["secondary_muscles_json"])
        ),
        met=row["met"],
        license=row["license"],
        attribution=row["attribution"],
        provenance=json.loads(row["provenance_json"]),
        content_hash=row["content_hash"],
        active=bool(row["active"]),
        aliases=tuple(filter(None, row["stored_aliases"].split(chr(31)))),
        is_favorite=bool(row["is_favorite"]),
        use_count=row["use_count"],
        last_used_at=row["last_used_at"],
        rank_group=row["rank_group"],
    )


def _exact_match_rank(row: sqlite3.Row, query: str) -> int:
    normalized_query = _normalized_search_term(query)
    if _normalized_search_term(row["name"]) == normalized_query:
        return 0
    aliases = filter(None, row["stored_aliases"].split(chr(31)))
    if any(_normalized_search_term(alias) == normalized_query for alias in aliases):
        return 1
    return 2


def _normalized_search_term(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00",
        "Z",
    )
