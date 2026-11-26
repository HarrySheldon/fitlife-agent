from __future__ import annotations

import atexit
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from threading import Lock
from typing import Any

import psycopg
from psycopg import pq
from psycopg.errors import RaiseException
from psycopg_pool import ConnectionPool

from backend.infrastructure.postgres.errors import (
    DatabaseError,
    DatabaseIntegrityError,
    DatabaseOperationalError,
)

_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_DOLLAR_TAG_RE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")

_POOLS: dict[tuple[str, str], ConnectionPool] = {}
_POOLS_GUARD = Lock()


def _validate_schema(schema: str | None) -> str | None:
    if schema is None:
        return None
    cleaned = schema.strip()
    if not cleaned:
        return None
    if _SCHEMA_RE.fullmatch(cleaned) is None:
        raise ValueError(f"Invalid PostgreSQL schema identifier: {schema!r}")
    return cleaned


class _HybridRow(Sequence[Any]):
    """Row supporting both column-name lookup (`row['id']`) and positional indexing (`row[0]`)."""

    __slots__ = ("_columns", "_values", "_index")

    def __init__(self, columns: tuple[str, ...], values: Sequence[Any]) -> None:
        self._columns = columns
        self._values = tuple(values)
        index: dict[str, int] = {}
        for pos, col in enumerate(columns):
            index.setdefault(col, pos)
        self._index = index

    def keys(self) -> tuple[str, ...]:
        return self._columns

    def get(self, key: str, default: Any = None) -> Any:
        pos = self._index.get(key)
        return default if pos is None else self._values[pos]

    def __getitem__(self, item: int | str | slice) -> Any:
        if isinstance(item, str):
            pos = self._index.get(item)
            if pos is None:
                raise IndexError(f"No column named {item!r}")
            return self._values[pos]
        return self._values[item]

    def __len__(self) -> int:
        return len(self._values)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _HybridRow):
            return self._columns == other._columns and self._values == other._values
        return NotImplemented

    def __repr__(self) -> str:
        pairs = ", ".join(f"{c}={v!r}" for c, v in zip(self._columns, self._values, strict=False))
        return f"Row({pairs})"


def _hybrid_row_factory(cursor: psycopg.Cursor[Any]):
    if cursor.description is None:
        return lambda values: tuple(values)
    columns = tuple(desc.name for desc in cursor.description)

    def make_row(values: Sequence[Any]) -> _HybridRow:
        return _HybridRow(columns, values)

    return make_row


def _translate_sql(sql: str, *, has_params: bool) -> str:
    """Convert `?` positional placeholders outside literals/comments/dollar-quotes to `%s`."""
    if not has_params or "?" not in sql:
        return sql

    out: list[str] = []
    n = len(sql)
    i = 0
    while i < n:
        ch = sql[i]
        # Single-line comment
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            end = sql.find("\n", i + 2)
            if end == -1:
                out.append(sql[i:])
                break
            out.append(sql[i : end + 1])
            i = end + 1
            continue
        # Block comment
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            end = sql.find("*/", i + 2)
            if end == -1:
                out.append(sql[i:])
                break
            out.append(sql[i : end + 2])
            i = end + 2
            continue
        # Single-quoted string literal
        if ch == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            segment = sql[i:j]
            out.append(segment.replace("%", "%%") if has_params else segment)
            i = j
            continue
        # Double-quoted identifier
        if ch == '"':
            j = i + 1
            while j < n:
                if sql[j] == '"':
                    if j + 1 < n and sql[j + 1] == '"':
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            segment = sql[i:j]
            out.append(segment.replace("%", "%%") if has_params else segment)
            i = j
            continue
        # Dollar-quoted block
        if ch == "$":
            match = _DOLLAR_TAG_RE.match(sql, i)
            if match is not None:
                tag = match.group(0)
                end = sql.find(tag, match.end())
                if end == -1:
                    out.append(sql[i:])
                    break
                segment = sql[i : end + len(tag)]
                out.append(segment.replace("%", "%%") if has_params else segment)
                i = end + len(tag)
                continue
        if ch == "?" and has_params:
            out.append("%s")
            i += 1
            continue
        if ch == "%" and has_params:
            if i + 1 < n and sql[i + 1] in ("s", "b", "t", "("):
                out.append(ch)
            else:
                out.append("%%")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _wrap_psycopg_error(error: psycopg.Error) -> DatabaseError:
    sqlstate = getattr(error, "sqlstate", None)
    diag = getattr(error, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None) if diag is not None else None
    table_name = getattr(diag, "table_name", None) if diag is not None else None
    if (
        isinstance(error, (psycopg.IntegrityError, RaiseException))
        or (sqlstate is not None and sqlstate.startswith("23"))
    ):
        return DatabaseIntegrityError(
            str(error),
            constraint_name=constraint_name,
            table_name=table_name,
            sqlstate=sqlstate,
        )
    if isinstance(error, psycopg.OperationalError):
        return DatabaseOperationalError(str(error), sqlstate=sqlstate)
    if sqlstate in {"42P01", "42703", "3F000", "57P01", "55P03", "40P01"}:
        return DatabaseOperationalError(str(error), sqlstate=sqlstate)
    return DatabaseError(str(error), sqlstate=sqlstate)


class _CursorProxy:
    def __init__(self, cursor: psycopg.Cursor[Any]) -> None:
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def description(self):
        return self._cursor.description

    def fetchone(self) -> _HybridRow | None:
        return self._cursor.fetchone()

    def fetchall(self) -> list[_HybridRow]:
        return self._cursor.fetchall()

    def fetchmany(self, size: int | None = None) -> list[_HybridRow]:
        if size is None:
            return self._cursor.fetchmany()
        return self._cursor.fetchmany(size)

    def __iter__(self) -> Iterator[_HybridRow]:
        return iter(self._cursor)


class PostgresConnection:
    """Pooled connection wrapper providing sqlite3-ergonomic `execute` and savepoints."""

    def __init__(self, raw: psycopg.Connection[Any], *, in_transaction: bool) -> None:
        self._raw = raw
        self._in_transaction = in_transaction

    @property
    def raw(self) -> psycopg.Connection[Any]:
        return self._raw

    def execute(
        self,
        sql: str,
        params: Sequence[Any] | Mapping[str, Any] | None = None,
    ) -> _CursorProxy:
        cursor = self._raw.cursor(row_factory=_hybrid_row_factory)
        try:
            if params is None:
                cursor.execute(_translate_sql(sql, has_params=False))
            elif isinstance(params, Mapping):
                cursor.execute(sql, params)
            elif len(params) == 0:
                cursor.execute(_translate_sql(sql, has_params=False))
            else:
                translated = _translate_sql(sql, has_params=True)
                cursor.execute(translated, tuple(params))
        except psycopg.Error as error:
            raise _wrap_psycopg_error(error) from error
        return _CursorProxy(cursor)

    def executemany(self, sql: str, seq_of_params: Sequence[Sequence[Any]]) -> _CursorProxy:
        cursor = self._raw.cursor(row_factory=_hybrid_row_factory)
        translated = _translate_sql(sql, has_params=True)
        try:
            cursor.executemany(translated, [tuple(p) for p in seq_of_params])
        except psycopg.Error as error:
            raise _wrap_psycopg_error(error) from error
        return _CursorProxy(cursor)

    @contextmanager
    def savepoint(self) -> Iterator[None]:
        if self._raw.info.transaction_status == pq.TransactionStatus.IDLE:
            yield
            return
        try:
            with self._raw.transaction():
                yield
        except DatabaseError:
            raise
        except psycopg.Error as error:
            raise _wrap_psycopg_error(error) from error

    def commit(self) -> None:
        if self._raw.info.transaction_status != pq.TransactionStatus.IDLE:
            self._raw.commit()

    def rollback(self) -> None:
        if self._raw.info.transaction_status != pq.TransactionStatus.IDLE:
            self._raw.rollback()


def _configure_pool_connection(schema: str | None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"autocommit": True}
    if schema is not None:
        kwargs["options"] = f"-c search_path={schema},public"
    return kwargs


def _pool_for(dsn: str, schema: str | None, *, min_size: int, max_size: int) -> ConnectionPool:
    key = (dsn, schema or "public")
    with _POOLS_GUARD:
        pool = _POOLS.get(key)
        if pool is None or pool.closed:
            pool = ConnectionPool(
                conninfo=dsn,
                min_size=min_size,
                max_size=max_size,
                timeout=10.0,
                open=True,
                kwargs=_configure_pool_connection(schema),
            )
            _POOLS[key] = pool
        return pool


def reset_database_pools() -> None:
    """Close and forget all cached PostgreSQL pools (primarily for tests/shutdown)."""
    with _POOLS_GUARD:
        pools = list(_POOLS.values())
        _POOLS.clear()
    for pool in pools:
        try:
            pool.close(timeout=2.0)
        except Exception:
            pass


atexit.register(reset_database_pools)


class PostgresDatabase:
    """Pooled PostgreSQL database entry point."""

    def __init__(
        self,
        dsn: str,
        *,
        schema: str | None = None,
        min_size: int = 1,
        max_size: int = 10,
    ) -> None:
        if not dsn or not isinstance(dsn, str):
            raise ValueError("PostgreSQL DSN must be a non-empty string")
        self.dsn = dsn
        self.schema = _validate_schema(schema)
        self.min_size = min_size
        self.max_size = max_size

    @property
    def target_schema(self) -> str:
        return self.schema or "public"

    def _pool(self) -> ConnectionPool:
        return _pool_for(
            self.dsn,
            self.schema,
            min_size=self.min_size,
            max_size=self.max_size,
        )

    @contextmanager
    def connection(self) -> Iterator[PostgresConnection]:
        try:
            with self._pool().connection() as raw:
                if self.schema is not None and raw.info.transaction_status == pq.TransactionStatus.IDLE:
                    raw.execute(f'SET search_path TO "{self.schema}", public')
                wrapper = PostgresConnection(raw, in_transaction=False)
                try:
                    yield wrapper
                finally:
                    if raw.info.transaction_status != pq.TransactionStatus.IDLE:
                        raw.rollback()
        except DatabaseError:
            raise
        except psycopg.Error as error:
            raise _wrap_psycopg_error(error) from error

    @contextmanager
    def transaction(self) -> Iterator[PostgresConnection]:
        try:
            with self._pool().connection() as raw:
                if self.schema is not None and raw.info.transaction_status == pq.TransactionStatus.IDLE:
                    raw.execute(f'SET search_path TO "{self.schema}", public')
                with raw.transaction():
                    yield PostgresConnection(raw, in_transaction=True)
        except DatabaseError:
            raise
        except psycopg.Error as error:
            raise _wrap_psycopg_error(error) from error

    def ping(self) -> bool:
        with self.connection() as conn:
            row = conn.execute("SELECT 1").fetchone()
            return row is not None and row[0] == 1

    def create_schema(self) -> None:
        if self.schema is None:
            return
        with self.connection() as conn:
            conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            ext_rows = conn.execute(
                "SELECT extname FROM pg_extension WHERE extname IN ('vector', 'pg_trgm')"
            ).fetchall()
            installed = {row[0] for row in ext_rows}
            if "vector" not in installed:
                conn.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
            if "pg_trgm" not in installed:
                conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public")

    def drop_schema(self) -> None:
        if self.schema is None:
            return
        key = (self.dsn, self.schema)
        with _POOLS_GUARD:
            pool = _POOLS.pop(key, None)
        if pool is not None:
            try:
                pool.close()
            except Exception:
                pass
        admin_db = PostgresDatabase(self.dsn)
        with admin_db.connection() as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
