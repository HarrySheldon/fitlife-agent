from __future__ import annotations


class DatabaseError(Exception):
    """Base database exception wrapping driver-level errors."""

    def __init__(self, message: str = "", *, sqlstate: str | None = None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


class DatabaseIntegrityError(DatabaseError):
    """Raised on UNIQUE, CHECK, FOREIGN KEY, NOT NULL, or trigger invariant violations."""

    def __init__(
        self,
        message: str = "",
        *,
        constraint_name: str | None = None,
        table_name: str | None = None,
        sqlstate: str | None = None,
    ) -> None:
        super().__init__(message, sqlstate=sqlstate)
        self.constraint_name = constraint_name
        self.table_name = table_name


class DatabaseOperationalError(DatabaseError):
    """Raised on connection, pool, lock, timeout, or undefined object errors."""
