"""One published shape per tool: arguments, effect, authorization, handler, replay.

The loop must not grow an ``if`` per tool. Everything a tool needs -- how its
arguments are validated, which domains the call requires, whether its output is
public, whether a failure may be retried -- lives in its spec, so adding a tool
is a registration and not an edit to the decision loop.

Two declarations are checked against each other instead of trusted:

* ``read_only`` must agree with ``effect``. A tool that writes drafts cannot
  advertise itself as read-only, and the published description is derived from
  the effect, so a model cannot influence it either.
* a ``draft_write`` must never be replayed by the runtime and must never be
  cached. Business idempotency comes from the task's operation id, not from a
  transport retry.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping

from pydantic import BaseModel

Effect = Literal["public_read", "private_read", "calculate", "draft_write"]
Replay = Literal["safe", "never"]

_NAME = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9]*)+$")
_MAX_RESULT_CEILING = 200_000


@dataclass(frozen=True)
class ToolAccess:
    """What an authorization hook may look at. Nothing here is model-controlled."""

    principal: Any
    args: Any
    domains: frozenset[str]
    required: frozenset[str]
    session: Any = None


@dataclass(frozen=True)
class ToolContext:
    """The smallest dependency set a handler needs.

    A handler never receives the repository itself, so it cannot choose an owner
    or reach a table the executor did not authorize.
    """

    catalog: Any
    reads: Any
    retriever: Any
    language: str
    evidence: Callable[[str], Mapping]
    domains: frozenset[str]


def require_domains(access: ToolAccess) -> None:
    """Default authorization: the call needs domains the principal still holds."""
    if not access.required <= access.domains:
        raise PermissionError("SCOPE_PERMISSION_REQUIRED")


def _no_domains(args: Any) -> frozenset[str]:
    return frozenset()


@dataclass(frozen=True)
class ToolSpec:
    name: str
    args_model: type[BaseModel]
    effect: Effect
    handler: Callable[[Any, ToolContext], Any]
    required_domains: Callable[[Any], frozenset[str]] = _no_domains
    authorize: Callable[[ToolAccess], None] = require_domains
    replay: Replay = "safe"
    read_only: bool = True
    cacheable: bool = False
    max_result_chars: int = 16000

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _NAME.match(self.name):
            raise ValueError("TOOL_NAME_INVALID")
        if self.effect not in ("public_read", "private_read", "calculate", "draft_write"):
            raise ValueError("TOOL_EFFECT_INVALID")
        if not (isinstance(self.args_model, type) and issubclass(self.args_model, BaseModel)):
            raise ValueError("TOOL_ARGS_MODEL_INVALID")
        if not callable(self.handler) or not callable(self.required_domains) or not callable(self.authorize):
            raise ValueError("TOOL_HANDLER_INVALID")
        if self.replay not in ("safe", "never"):
            raise ValueError("TOOL_REPLAY_INVALID")
        if type(self.read_only) is not bool:
            raise ValueError("TOOL_READ_ONLY_INVALID")
        if self.read_only != (self.effect != "draft_write"):
            # The description a model sees is derived from the effect, so a
            # contradiction here would publish a write as a read.
            raise ValueError("TOOL_READ_ONLY_CONTRADICTION")
        if self.effect == "draft_write" and self.replay != "never":
            raise ValueError("DRAFT_WRITE_MUST_NOT_REPLAY")
        if self.effect == "draft_write" and self.cacheable:
            raise ValueError("DRAFT_WRITE_MUST_NOT_CACHE")
        if type(self.max_result_chars) is not int or not 1 <= self.max_result_chars <= _MAX_RESULT_CEILING:
            raise ValueError("TOOL_RESULT_LIMIT_INVALID")

    @property
    def public(self) -> bool:
        return self.effect == "public_read"

    def describe(self) -> dict:
        return {"name": self.name, "parameters": self.args_model.model_json_schema(),
                "read_only": self.effect != "draft_write"}
