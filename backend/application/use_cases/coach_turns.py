"""Turn admission, execution and publication for the coach surface.

The service is the only place that decides whether a model call may start. That
decision is made in one write transaction (``accept_turn``), so two requests with
different idempotency keys cannot both start: the loser is refused, not queued.

Three rules shape the code below.

*No transaction across generation.* Acceptance commits before the answer port is
called; publication is a separate transaction afterwards. Holding a write
transaction open for the length of a model call would serialize every account
behind one slow provider.

*Cancellation closes the transport.* ``cancel`` records intent, then aborts the
run's registry, which closes the gateway's private HTTP client. The worker exits,
and only then is the turn published as cancelled — so the slot is not released
while a request is still in flight.

*Publication is conditional.* The repository re-checks ownership, deletion,
cancellation, expiry, version and review. A late answer that fails any check is
discarded rather than written.
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

from backend.application.ports.coach_answer import CoachAnswerPort, CoachTurnRequest
from backend.application.ports.coach_conversation_repository import (
    CoachConversationRepository,
    TurnRecord,
)
from backend.application.ports.model_call_context import AbortRegistry, current_abort
from backend.domain.coach_conversation import TERMINAL_TURN_STATUSES, CoachMessage
from backend.domain.coach_turn import TurnNotCancellable
from backend.domain.user_preferences import UserPreferences

LEGACY_CONVERSATION_PREFIX = "system:"


class LegacyAnswerDiscarded(RuntimeError):
    """A synchronous answer finished after the account stopped owning it."""

    code = "COACH_TURN_SUPERSEDED"


@dataclass(frozen=True)
class TurnSubmission:
    turn: TurnRecord
    replayed: bool
    """True when the idempotency key matched an existing turn; nothing restarted."""


@dataclass
class _Execution:
    abort: AbortRegistry = field(default_factory=AbortRegistry)
    future: Future | None = None


def _fingerprint(**fields) -> str:
    """Stable over the fields that make one request distinct from another."""
    canonical = json.dumps(fields, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CoachTurnService:
    def __init__(
        self,
        repository: CoachConversationRepository,
        answers: CoachAnswerPort,
        *,
        clock=None,
        lease_id: str | None = None,
        executor: Executor | None = None,
    ) -> None:
        self.repository = repository
        self.answers = answers
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.lease_id = lease_id or uuid4().hex
        self._owns_executor = executor is None
        self.executor = executor or ThreadPoolExecutor(
            max_workers=8, thread_name_prefix="coach-turn"
        )
        self._running: dict[str, _Execution] = {}
        self._lock = Lock()

    # -- public surface --------------------------------------------------
    def submit(
        self,
        user_id: str,
        conversation_id: str,
        *,
        idempotency_key: str,
        question: str,
        action: str,
        surface: str,
        date: str | None = None,
        language: str = "en-US",
        answer_mode: str = "brief",
        preferences: UserPreferences | None = None,
        plan_id: str | None = None,
        report_week: str | None = None,
    ) -> TurnSubmission:
        """Admit one turn and start it in the background.

        The response is the accepted turn, not the answer. A client that loses the
        connection can re-read the turn by id; it does not have to re-ask.
        """
        fingerprint = _fingerprint(
            question=question,
            action=action,
            surface=surface,
            date=date,
            language=language,
            answer_mode=answer_mode,
            plan_id=plan_id, report_week=report_week,
        )
        generated = uuid4().hex
        now = self.clock()
        turn = self.repository.accept_turn(
            user_id,
            conversation_id,
            turn_id=generated,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            created_at=now,
            request_context={"action": action, "surface": surface, "date": date,
                "plan_id": plan_id, "report_week": report_week,
                "language": language, "answer_mode": answer_mode},
        )
        if turn.turn_id != generated:
            # A retry of the same request. It may still be running, and it must not
            # produce a second model call.
            return TurnSubmission(turn=turn, replayed=True)

        request = CoachTurnRequest(
            user_id=user_id,
            conversation_id=conversation_id,
            turn_id=turn.turn_id,
            question=question,
            action=action,
            surface=surface,
            date=date,
            language=language,
            answer_mode=answer_mode,
            request_id=turn.turn_id,
            preferences=preferences or UserPreferences(),
            plan_id=plan_id, report_week=report_week,
        )
        try:
            self.repository.append_message(
                user_id,
                CoachMessage(
                    message_id=f"{turn.turn_id}-user",
                    conversation_id=conversation_id,
                    turn_id=turn.turn_id,
                    role="user",
                    body=question,
                    created_at=now,
                ),
            )
        except Exception:
            # The turn exists but has no question; it must not hold the slot.
            self.repository.publish_turn(
                user_id,
                turn.turn_id,
                status="failed",
                updated_at=self.clock(),
                error_code="TURN_NOT_STORED",
            )
            raise
        self._start(user_id, turn.turn_id, request)
        return TurnSubmission(turn=turn, replayed=False)

    def cancel(self, user_id: str, turn_id: str) -> TurnRecord:
        """Stop a turn. Returns as soon as intent is recorded.

        The slot stays taken until the worker closes its transport and publishes
        the terminal state, so the caller must poll the turn rather than assume
        the slot is free the moment this returns.
        """
        turn = self.repository.get_turn(user_id, turn_id)
        if turn.status in TERMINAL_TURN_STATUSES:
            raise TurnNotCancellable("the turn has already finished")
        if turn.status == "awaiting_user":
            # Nothing is executing, so there is no transport to close.
            self.repository.publish_turn(
                user_id, turn_id, status="cancelled", updated_at=self.clock()
            )
            return self.repository.get_turn(user_id, turn_id)

        stopping = self.repository.request_cancel(user_id, turn_id, at=self.clock())
        execution = self._execution(turn_id)
        if execution is not None:
            execution.abort.abort()
        return stopping

    def wait(self, turn_id: str, *, timeout: float | None = None) -> None:
        execution = self._execution(turn_id)
        if execution is not None and execution.future is not None:
            execution.future.result(timeout=timeout)

    def active(self, user_id: str) -> TurnRecord | None:
        return self.repository.active_turn(user_id)

    # -- legacy quick actions -------------------------------------------
    def begin_legacy(
        self,
        user_id: str,
        *,
        question: str,
        action: str,
        surface: str,
    ) -> TurnRecord:
        """Take the same slot for a synchronous quick action.

        The legacy endpoint keeps producing its own answer and response shape, but
        it may not run while a conversation turn holds the slot, and a conversation
        turn may not start while it does.
        """
        conversation_id = self._system_conversation(user_id)
        now = self.clock()
        turn = self.repository.accept_turn(
            user_id,
            conversation_id,
            turn_id=uuid4().hex,
            idempotency_key=uuid4().hex,
            request_fingerprint=_fingerprint(
                question=question, action=action, surface=surface, legacy=True
            ),
            created_at=now,
        )
        try:
            self.repository.append_message(
                user_id,
                CoachMessage(
                    message_id=f"{turn.turn_id}-user",
                    conversation_id=conversation_id,
                    turn_id=turn.turn_id,
                    role="user",
                    body=question or action,
                    created_at=now,
                ),
            )
        except Exception:
            self.repository.publish_turn(
                user_id, turn.turn_id, status="failed", updated_at=now,
                error_code="TURN_NOT_STORED",
            )
            raise
        return self.repository.claim_turn(
            user_id, turn.turn_id, lease_id=self.lease_id, started_at=now
        )

    def run_legacy(
        self,
        user_id: str,
        *,
        question: str,
        action: str,
        surface: str,
        produce,
    ) -> dict:
        """Run a synchronous quick action under the same single slot.

        The legacy endpoints keep their own answer pipeline and response shape;
        what they may not keep is a private path to the model. Wrapping them here
        means "take the slot, produce, publish, or fail" has exactly one
        implementation, so a new legacy caller cannot forget one of the steps.
        """
        turn = self.begin_legacy(
            user_id, question=question, action=action, surface=surface
        )
        execution = _Execution()
        with self._lock:
            self._running[turn.turn_id] = execution
        token = current_abort.set(execution.abort)
        try:
            latest = self.repository.get_turn(user_id, turn.turn_id)
            if latest.cancel_requested_at is not None or execution.abort.aborted:
                execution.abort.abort()
                raise LegacyAnswerDiscarded("the request was cancelled before production")
            result = produce()
        except BaseException as error:  # noqa: BLE001 - the slot must always be freed
            self._finish_failed(user_id, turn.turn_id, execution, error)
            raise
        finally:
            current_abort.reset(token)
            with self._lock:
                self._running.pop(turn.turn_id, None)
        published = self.finish_legacy(
            user_id,
            turn,
            answer_markdown=str(result.get("answer_markdown") or ""),
            model=str(result.get("model") or ""),
        )
        if not published:
            # The account was deleted or the turn was stopped while the model ran.
            # The answer is dropped rather than returned to a client whose account
            # no longer owns it.
            self._finish_failed(user_id, turn.turn_id, execution, LegacyAnswerDiscarded())
            raise LegacyAnswerDiscarded("the answer was no longer publishable")
        return result

    def finish_legacy(
        self, user_id: str, turn: TurnRecord, *, answer_markdown: str, model: str
    ) -> bool:
        return self.repository.complete_turn(
            user_id,
            turn.turn_id,
            message=CoachMessage(
                message_id=f"{turn.turn_id}-coach",
                conversation_id=turn.conversation_id,
                turn_id=turn.turn_id,
                role="coach",
                body=answer_markdown,
                created_at=self.clock(),
                review_status="approved",
            ),
            updated_at=self.clock(),
            expected_version=turn.version,
            receipt_json=json.dumps({"model": model}, ensure_ascii=False),
        )

    def fail_legacy(self, user_id: str, turn: TurnRecord, *, error_code: str) -> None:
        self.repository.publish_turn(
            user_id,
            turn.turn_id,
            status="failed",
            updated_at=self.clock(),
            expected_version=turn.version,
            error_code=error_code,
        )

    # -- account lifecycle ----------------------------------------------
    def cancel_active_for_account(self, user_id: str) -> TurnRecord | None:
        """Logout, revocation and deletion stop work; closing a window does not."""
        active = self.repository.active_turn(user_id)
        if active is None:
            return None
        # Account lifecycle is owner-scoped but not a public transcript read.
        # A deleted chat may still own the slot while its transport cleans up.
        try:
            stopping = self.repository.request_cancel(user_id, active.turn_id, at=self.clock())
        except (KeyError, TurnNotCancellable):
            return None  # Completion/account removal won the race.
        execution = self._execution(active.turn_id)
        if execution is not None:
            execution.abort.abort()
        return stopping

    def delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        deleted = self.repository.delete_conversation(
            user_id, conversation_id, deleted_at=self.clock()
        )
        active = self.repository.active_turn(user_id)
        if active is not None and active.conversation_id == conversation_id:
            execution = self._execution(active.turn_id)
            if execution is not None:
                execution.abort.abort()
        return deleted

    # -- execution -------------------------------------------------------
    def _start(self, user_id: str, turn_id: str, request: CoachTurnRequest) -> None:
        execution = _Execution()
        with self._lock:
            self._running[turn_id] = execution
        execution.future = self.executor.submit(self._run, user_id, turn_id, request, execution)

    def _run(
        self, user_id: str, turn_id: str, request: CoachTurnRequest, execution: _Execution
    ) -> None:
        token = current_abort.set(execution.abort)
        try:
            claimed = self.repository.claim_turn(
                user_id, turn_id, lease_id=self.lease_id, started_at=self.clock()
            )
            if claimed.cancel_requested_at is not None or execution.abort.aborted:
                execution.abort.abort()
                raise RuntimeError("the request was cancelled before production")
            from backend.application.use_cases.coach_conversations import CoachConversations
            from backend.safety.business_scope import decide_business_scope, is_closed_followup, followup_policy_question
            from backend.domain.coach_answer import ACTION_REGISTRY
            projection = CoachConversations(self.repository, clock=self.clock).context(
                user_id, conversation_id=request.conversation_id, turn_id=turn_id,
            )
            previous = next((item for item in reversed(projection.messages) if item.role == "user"), None)
            if request.action == "chat" and is_closed_followup(request.question) and previous and previous.admitted_scope:
                reference = previous.context_ref
                if reference.get("action") in ACTION_REGISTRY and reference.get("surface") in {"today", "profile", "plan", "review", "logbook"}:
                    request = replace(request, action=reference["action"], surface=reference["surface"],
                        plan_id=reference.get("plan_id"), report_week=reference.get("report_week"),
                        date=reference.get("date"), answer_mode="detailed")
            admitted_scope = request.action in ACTION_REGISTRY or decide_business_scope(request.question).scope == "in_scope"
            if is_closed_followup(request.question):
                admitted_scope = admitted_scope or followup_policy_question(request.question,
                    tuple({"role": item.role, "body": item.body, "admitted_scope": item.admitted_scope} for item in projection.messages)) != request.question
            answer = self.answers.run(request)
            from backend.domain.coach_answer import limits_for_or_default
            if len(answer.answer_markdown) > limits_for_or_default(request.action, request.answer_mode).body_chars:
                from backend.domain.errors import ApplicationError
                raise ApplicationError(code="COACH_ANSWER_TOO_LONG", message="The answer exceeded its output contract.", status_code=502)
            if answer.review_status != "approved":
                # Fail closed: an unreviewed draft is never written, not even
                # hidden behind a pending flag.
                self.repository.publish_turn(
                    user_id,
                    turn_id,
                    status="failed",
                    updated_at=self.clock(),
                    error_code="ANSWER_NOT_APPROVED",
                )
                return
            completed = self.repository.complete_turn(
                user_id,
                turn_id,
                message=CoachMessage(
                    message_id=f"{turn_id}-coach",
                    conversation_id=request.conversation_id,
                    turn_id=turn_id,
                    role="coach",
                    body=answer.answer_markdown,
                    created_at=self.clock(),
                    review_status="approved",
                ),
                updated_at=self.clock(),
                expected_version=claimed.version,
                receipt_json=json.dumps(
                    {"model": answer.model, "trace": answer.trace, "sources": answer.sources,
                     # Display-only handoff for a business task. The business service
                     # remains the only owner of candidates, budgets and permissions.
                     "business_task_ref": answer.trace.get("business_task_ref") if isinstance(answer.trace, dict) else None,
                     "context": {"action": request.action, "date": request.date,
                                 "plan_id": request.plan_id, "report_week": request.report_week,
                                 "surface": request.surface, "language": request.language,
                                 "answer_mode": request.answer_mode, "admitted_scope": admitted_scope}},
                    ensure_ascii=False, default=str
                ),
            )
            if not completed:
                # A cancel, a deletion, an expiry or a moved version won the race.
                # The answer was never written.
                self._finish_failed(
                    user_id,
                    turn_id,
                    execution,
                    RuntimeError("the answer was not publishable"),
                )
        except BaseException as error:  # noqa: BLE001 - the turn must reach a terminal state
            self._finish_failed(user_id, turn_id, execution, error)
        finally:
            current_abort.reset(token)
            with self._lock:
                self._running.pop(turn_id, None)

    def _finish_failed(
        self, user_id: str, turn_id: str, execution: _Execution, error: BaseException
    ) -> None:
        try:
            turn = self.repository.get_turn(user_id, turn_id)
        except KeyError:
            # Public reads deliberately hide tombstoned conversations. The worker
            # has now unwound, so it can finalize cancellation without reading the
            # deleted transcript. A deleted account may have removed the row too.
            try:
                self.repository.publish_turn(
                    user_id, turn_id, status="cancelled", updated_at=self.clock()
                )
            except KeyError:
                pass
            return
        if turn.status in TERMINAL_TURN_STATUSES:
            return
        cancelled = execution.abort.aborted or turn.cancel_requested_at is not None
        self.repository.publish_turn(
            user_id,
            turn_id,
            status="cancelled" if cancelled else "failed",
            updated_at=self.clock(),
            error_code=None if cancelled else _error_code(error),
        )

    def _execution(self, turn_id: str) -> _Execution | None:
        with self._lock:
            return self._running.get(turn_id)

    def _system_conversation(self, user_id: str) -> str:
        conversation_id = f"{LEGACY_CONVERSATION_PREFIX}{user_id}"
        try:
            self.repository.get_conversation(user_id, conversation_id)
        except KeyError:
            try:
                self.repository.create_conversation(
                    user_id,
                    conversation_id=conversation_id,
                    title="Quick actions",
                    created_at=self.clock(),
                    kind="system",
                )
            except Exception:
                # Another request created it first; reading it is enough.
                self.repository.get_conversation(user_id, conversation_id)
        return conversation_id

    def close(self) -> None:
        if self._owns_executor:
            self.executor.shutdown(wait=False)


def _error_code(error: BaseException) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and code.isupper() and code.isascii():
        return code[:64]
    return "COACH_TURN_FAILED"
