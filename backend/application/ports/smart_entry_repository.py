from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Literal, Protocol, runtime_checkable

from backend.domain.smart_entry import ResolvedCandidate
from backend.domain.entry_interaction import EntryInteraction, project_interaction


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
    interaction: EntryInteraction | None = None

    def __post_init__(self) -> None:
        if self.interaction is None and len({item.id for item in self.candidates}) == len(self.candidates):
            object.__setattr__(self, 'interaction', project_interaction(self.candidates))


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


@dataclass(frozen=True)
class EntryItemCommit:
    item_id: str
    item_revision: int
    meal_id: str
    meal_item_id: str
    record_state: Literal['unchanged', 'changed', 'deleted'] = 'unchanged'


@dataclass(frozen=True)
class ConfirmedEntryItems:
    draft_id: str
    commits: tuple[EntryItemCommit, ...]
    remaining_draft_version: int
    replayed: bool = False


@runtime_checkable
class SmartEntryRepository(Protocol):
    def list_entry_item_commits(self, user_id: str, draft_id: str) -> tuple[EntryItemCommit, ...]: ...

    def confirm_items(self, user_id: str, draft_id: str, *, expected_version: int,
                      selections, idempotency_key: str, request_fingerprint: str,
                      timezone_name: str = 'UTC', accepted_estimates=()) -> ConfirmedEntryItems: ...

    def get_interaction_command_result(
        self, user_id: str, draft_id: str, *, idempotency_key: str,
        request_fingerprint: str,
    ) -> SmartEntryDraft | None: ...

    def read_interaction_draft(self, user_id: str, draft_id: str) -> SmartEntryDraft: ...

    def execute_interaction_command(
        self, user_id: str, draft_id: str, *, expected_version: int,
        idempotency_key: str, request_fingerprint: str,
        transform: Callable[[SmartEntryDraft], SmartEntryDraftPayload],
    ) -> SmartEntryDraft: ...

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
