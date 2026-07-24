from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from backend.application.ports.food_catalog_repository import (
    FoodCatalogItem,
    FoodCatalogRepositoryError,
    NewCustomFood,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase


Clock = Callable[[], datetime]
IdFactory = Callable[[], str]
_VISIBLE_FOOD = """
    food.active = 1
    AND (food.owner_user_id IS NULL OR food.owner_user_id = ?)
"""
_SEARCH_SELECT = """
    SELECT
        food.*,
        COALESCE(favorite.is_favorite, 0) AS is_favorite,
        COALESCE(usage.use_count, 0) AS use_count,
        usage.last_used_at,
        CASE
            WHEN usage.food_id IS NOT NULL THEN 0
            WHEN favorite.food_id IS NOT NULL THEN 1
            WHEN food.owner_user_id IS NOT NULL THEN 2
            ELSE 3
        END AS rank_group,
        COALESCE((
            SELECT group_concat(ordered_alias.alias, char(31))
            FROM (
                SELECT alias
                FROM catalog_aliases
                WHERE food_id = food.id
                ORDER BY rowid
            ) AS ordered_alias
        ), '') AS stored_aliases
    FROM food_catalog AS food
    LEFT JOIN (
        SELECT food_id, 1 AS is_favorite
        FROM catalog_favorites
        WHERE user_id = ? AND food_id IS NOT NULL
    ) AS favorite ON favorite.food_id = food.id
    LEFT JOIN (
        SELECT food_id, use_count, last_used_at
        FROM catalog_usage
        WHERE user_id = ? AND food_id IS NOT NULL
    ) AS usage ON usage.food_id = food.id
"""
_RANK_ORDER = """
    ORDER BY
        rank_group,
        CASE WHEN usage.food_id IS NOT NULL THEN usage.last_used_at END DESC,
        usage.use_count DESC,
        lower(food.name),
        food.name,
        food.id
    LIMIT ?
"""


class SQLiteFoodCatalogRepository:
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
    ) -> tuple[FoodCatalogItem, ...]:
        match_query = _fts_query(query)
        with self.database.connection() as connection:
            if match_query:
                rows = connection.execute(
                    f"""
                    {_SEARCH_SELECT}
                    WHERE {_VISIBLE_FOOD}
                      AND food.id IN (
                          SELECT catalog_id
                          FROM catalog_search
                          WHERE catalog_kind = 'food'
                            AND catalog_search MATCH ?
                      )
                    {_RANK_ORDER}
                    """,
                    (user_id, user_id, user_id, match_query, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    f"""
                    {_SEARCH_SELECT}
                    WHERE {_VISIBLE_FOOD}
                    {_RANK_ORDER}
                    """,
                    (user_id, user_id, user_id, limit),
                ).fetchall()
        return tuple(_item_from_row(row) for row in rows)

    def set_favorite(
        self,
        user_id: str,
        food_id: str,
        favorite: bool,
    ) -> None:
        with self.database.transaction() as connection:
            _require_visible_food(connection, user_id, food_id)
            if favorite:
                connection.execute(
                    """
                    INSERT INTO catalog_favorites (id, user_id, food_id)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, food_id) WHERE food_id IS NOT NULL
                    DO NOTHING
                    """,
                    (self._id_factory(), user_id, food_id),
                )
            else:
                connection.execute(
                    """
                    DELETE FROM catalog_favorites
                    WHERE user_id = ? AND food_id = ?
                    """,
                    (user_id, food_id),
                )

    def create_custom_food(
        self,
        user_id: str,
        food: NewCustomFood,
    ) -> FoodCatalogItem:
        definition = food.definition
        if definition.source != "user_custom":
            raise FoodCatalogRepositoryError("CUSTOM_FOOD_SOURCE_INVALID")
        food_id = self._id_factory()
        aliases = _unique_aliases(food.aliases)
        created_at = _utc_timestamp(self._clock())
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO food_catalog (
                    id, owner_user_id, source, source_name, source_record_id,
                    name, basis_type, basis_amount, unit, calories, carbs,
                    protein, fat, provenance_json, created_at, updated_at
                ) VALUES (
                    ?, ?, 'user_custom', 'user-custom', ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, '{"entry_method":"form"}', ?, ?
                )
                """,
                (
                    food_id,
                    user_id,
                    food_id,
                    definition.name.strip(),
                    definition.basis_type,
                    definition.basis_amount,
                    definition.unit.strip(),
                    definition.calories,
                    definition.carbs,
                    definition.protein,
                    definition.fat,
                    created_at,
                    created_at,
                ),
            )
            for alias in aliases:
                connection.execute(
                    """
                    INSERT INTO catalog_aliases (
                        id, food_id, alias, normalized_alias, alias_kind
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        self._id_factory(),
                        food_id,
                        alias,
                        _normalize_alias(alias),
                        _alias_kind(alias),
                    ),
                )
            _replace_search_row(
                connection,
                food_id=food_id,
                name=definition.name.strip(),
                aliases=aliases,
                source_tokens="user custom",
            )
        created = self._get_visible_food(user_id, food_id)
        if created is None:
            raise FoodCatalogRepositoryError("CUSTOM_FOOD_CREATE_FAILED")
        return created

    def record_usage(self, user_id: str, food_id: str) -> None:
        used_at = _utc_timestamp(self._clock())
        with self.database.transaction() as connection:
            _require_visible_food(connection, user_id, food_id)
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
                (self._id_factory(), user_id, food_id, used_at),
            )

    def _get_visible_food(
        self,
        user_id: str,
        food_id: str,
    ) -> FoodCatalogItem | None:
        with self.database.connection() as connection:
            row = connection.execute(
                f"""
                {_SEARCH_SELECT}
                WHERE {_VISIBLE_FOOD}
                  AND food.id = ?
                """,
                (user_id, user_id, user_id, food_id),
            ).fetchone()
        return _item_from_row(row) if row is not None else None


def _fts_query(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    tokens = re.findall(r"[\w\u3400-\u9fff]+", normalized)
    terms: list[str] = []
    for token in tokens[:8]:
        clean = token.replace(chr(34), "")
        if re.fullmatch(r"[\u3400-\u9fff]{2,}", clean):
            terms.extend(
                f'"{clean[index:index + 2]}"*'
                for index in range(len(clean) - 1)
            )
        else:
            terms.append(f'"{clean}"*')
    return " AND ".join(terms)


def _unique_aliases(aliases: tuple[str, ...]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for raw_alias in aliases:
        if not isinstance(raw_alias, str):
            raise FoodCatalogRepositoryError("FOOD_ALIAS_INVALID")
        alias = unicodedata.normalize("NFKC", raw_alias).strip()
        normalized = _normalize_alias(alias)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(alias)
    return tuple(unique)


def _normalize_alias(alias: str) -> str:
    return unicodedata.normalize("NFKC", alias).strip().casefold()


def _alias_kind(alias: str) -> str:
    if re.search(r"[\u3400-\u9fff]", alias):
        return "zh"
    return "en"


def _replace_search_row(
    connection: sqlite3.Connection,
    *,
    food_id: str,
    name: str,
    aliases: tuple[str, ...],
    source_tokens: str,
) -> None:
    connection.execute(
        """
        DELETE FROM catalog_search
        WHERE catalog_kind = 'food' AND catalog_id = ?
        """,
        (food_id,),
    )
    connection.execute(
        """
        INSERT INTO catalog_search (
            catalog_kind, catalog_id, name, aliases, pinyin, source_tokens
        ) VALUES ('food', ?, ?, ?, ?, ?)
        """,
        (
            food_id,
            name,
            " ".join(aliases),
            " ".join(alias for alias in aliases if _alias_kind(alias) == "en"),
            _source_tokens(name, aliases, source_tokens),
        ),
    )


def _source_tokens(
    name: str,
    aliases: tuple[str, ...],
    source_tokens: str,
) -> str:
    tokens = re.findall(
        r"[A-Za-z0-9_]+|[\u3400-\u9fff]+",
        unicodedata.normalize("NFKC", " ".join((name, *aliases))),
    )
    expanded = source_tokens.split()
    for token in tokens:
        normalized = token.casefold()
        expanded.append(normalized)
        if re.fullmatch(r"[\u3400-\u9fff]+", normalized):
            expanded.extend(
                normalized[index : index + 2]
                for index in range(max(0, len(normalized) - 1))
            )
    return " ".join(dict.fromkeys(expanded))


def _require_visible_food(
    connection: sqlite3.Connection,
    user_id: str,
    food_id: str,
) -> None:
    row = connection.execute(
        """
        SELECT 1
        FROM food_catalog
        WHERE id = ?
          AND active = 1
          AND (owner_user_id IS NULL OR owner_user_id = ?)
        """,
        (food_id, user_id),
    ).fetchone()
    if row is None:
        raise FoodCatalogRepositoryError("FOOD_NOT_VISIBLE")


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _item_from_row(row: sqlite3.Row) -> FoodCatalogItem:
    aliases = tuple(filter(None, row["stored_aliases"].split(chr(31))))
    return FoodCatalogItem(
        id=row["id"],
        owner_user_id=row["owner_user_id"],
        source=row["source"],
        source_name=row["source_name"],
        source_record_id=row["source_record_id"],
        dataset_version=row["dataset_version"],
        name=row["name"],
        basis_type=row["basis_type"],
        basis_amount=row["basis_amount"],
        unit=row["unit"],
        calories=row["calories"],
        carbs=row["carbs"],
        protein=row["protein"],
        fat=row["fat"],
        license=row["license"],
        attribution=row["attribution"],
        provenance=json.loads(row["provenance_json"]),
        content_hash=row["content_hash"],
        active=bool(row["active"]),
        aliases=aliases,
        is_favorite=bool(row["is_favorite"]),
        use_count=row["use_count"],
        last_used_at=row["last_used_at"],
        rank_group=row["rank_group"],
    )
