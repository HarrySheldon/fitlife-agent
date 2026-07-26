from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from backend.domain.smart_entry import ResolvedCandidate


AgentStatus = Literal["not_requested", "running", "completed", "failed"]


class SmartEntryRepositoryError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SmartEntryDraftPayload:
    log_date: str
    raw_text: str
    parser_version: str
    candidates: tuple[ResolvedCandidate, ...]


@dataclass(frozen=True)
class SmartEntryDraft:
    id: str
    user_id: str
    payload: SmartEntryDraftPayload
    version: int
    agent_status: AgentStatus
    agent_prompt_version: str | None
    agent_model: str | None
    agent_metadata: dict[str, object]
    expires_at: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ConfirmedSmartEntry:
    draft_id: str
    log_date: str
    meal_ids: tuple[str, ...]
    training_session_id: str | None
    replayed: bool = False


@runtime_checkable
class SmartEntryRepository(Protocol):
    def create_draft(
        self,
        user_id: str,
        payload: SmartEntryDraftPayload,
        *,
        expires_at: str,
    ) -> SmartEntryDraft: ...

    def get_draft(
        self,
        user_id: str,
        draft_id: str,
    ) -> SmartEntryDraft | None: ...

    def find_latest_draft(
        self,
        user_id: str,
        log_date: str,
    ) -> SmartEntryDraft | None: ...

    def update_draft(
        self,
        user_id: str,
        draft_id: str,
        *,
        expected_version: int,
        payload: SmartEntryDraftPayload,
    ) -> SmartEntryDraft: ...

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
    ) -> SmartEntryDraft: ...

    def mark_agent_failed(
        self,
        user_id: str,
        draft_id: str,
        *,
        expected_version: int,
        prompt_version: str,
        model: str | None,
        metadata: dict[str, object],
    ) -> SmartEntryDraft: ...

    def confirm(
        self,
        user_id: str,
        draft_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
        request_fingerprint: str,
        timezone_name: str = "UTC",
    ) -> ConfirmedSmartEntry: ...

    def delete_draft(self, user_id: str, draft_id: str) -> None: ...
