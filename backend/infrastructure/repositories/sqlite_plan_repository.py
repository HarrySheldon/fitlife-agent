"""Official plan history, one head per owner, and the confirmation transaction.

Three properties are enforced here because they cannot be enforced anywhere else.

**History is insert-only.** A plan id names one document for good. Writing the
same id with the same bytes is a no-op (so an import can be repeated); writing it
with different bytes is a conflict, because "the plan the user saw yesterday"
must still be there tomorrow.

**The head moves by compare-and-swap.** ``UPDATE plan_heads ... WHERE revision =
expected`` is the second guard behind the read of the same row earlier in the
transaction. A process-local lock would not help: the two confirmations this must
stop can be in different processes.

**The confirmation is one transaction.** Receipt, task, candidate, head, history
and the activated state all move together or not at all, so a crash between the
plan insert and the receipt cannot leave a plan nobody can retry into.

The repository never constructs a model and never decides whether a plan is good.
The caller supplies ``verify``, which runs *inside* the transaction against the
bytes about to be written and returns the exact document to store.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from backend.application.ports.plan_adjustment_repository import TERMINAL_STATES
from backend.application.ports.plan_repository import (
    ActivationContext,
    PlanActivationReceipt,
    PlanHead,
    StoredPlan,
    StoredPlanDraft,
    Verifier,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase


def _task_error(code: str):
    from backend.agent.tasks.contracts import task_error
    return task_error(code)


# The confirmation contract owns these codes. They are listed here rather than
# added to ``task_error``'s map because that map is the *task* contract, shared
# with callers that never touch plan history.
_STATUS = {
    "PLAN_BASE_STALE": 409,
    "PLAN_HISTORY_CONFLICT": 409,
    "CANDIDATE_EXPIRED": 410,
    "CANDIDATE_DIGEST_MISMATCH": 409,
    "CANDIDATE_DOCUMENT_MISSING": 409,
    "CHANGE_DOMAIN_NOT_AUTHORIZED": 403,
}


def _plan_error(code: str):
    from backend.domain.errors import ApplicationError
    return ApplicationError(code=code, message=code, status_code=_STATUS[code],
                            processing_mode="agent")


def _identity(*values: str) -> None:
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError("PLAN_TASK_IDENTITY_REQUIRED")


def _positive_int(value: int, name: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"PLAN_TASK_FIELD_INVALID:{name}")


def _fingerprint(payload) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _content_digest(document: Mapping[str, Any]) -> str:
    return _fingerprint(dict(document))


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class SQLitePlanRepository:
    def __init__(self, database: SQLiteDatabase, *, clock=None, ids=None,
                 constraints_reader=None) -> None:
        self.database = database
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._ids = ids or (lambda: uuid4().hex)
        # ``constraints_reader(connection, user_id) -> ConstraintSnapshot``. It
        # takes the transaction's own connection on purpose: a snapshot read on a
        # second connection describes whatever was committed a moment ago, which
        # is exactly the profile this confirmation is supposed to be checking
        # against. Absent means the deployment cannot version its constraints, and
        # the verifier refuses on that rather than approving blind.
        self.constraints_reader = constraints_reader

    # ------------------------------------------------------------------ history

    def save(self, user_id: str, plan: StoredPlan) -> None:
        """Record an activated plan and move the head to it.

        ``save`` is the activation path, so it advances the head. The legacy
        import is *not* this method: imported plans are history, and the head of a
        migrated directory is computed once from all of them (see ``import_plan``
        and ``set_head``).
        """
        _identity(user_id, plan.plan_id)
        with self.database.transaction() as connection:
            if not self._insert_plan(connection, user_id, plan, self.clock()):
                # Same id, same bytes: the caller is retrying, and a retry must not
                # spend a second head revision.
                return
            head = self._head(connection, user_id)
            self._advance_head(connection, user_id, plan.plan_id,
                               (head.revision if head else 0) + 1, self.clock())

    def list(self, user_id: str) -> list[StoredPlan]:
        _identity(user_id)
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM plans WHERE user_id=? "
                "ORDER BY activated_at DESC, plan_id DESC",
                (user_id,),
            ).fetchall()
            return [self._plan_from_row(row) for row in rows]

    def get(self, user_id: str, plan_id: str) -> StoredPlan | None:
        _identity(user_id, plan_id)
        with self.database.connection() as connection:
            return self._plan(connection, user_id, plan_id)

    def current_head(self, user_id: str) -> PlanHead | None:
        _identity(user_id)
        with self.database.connection() as connection:
            return self._head(connection, user_id)

    # ------------------------------------------------------------------- drafts

    def save_draft(self, user_id: str, draft: StoredPlanDraft) -> None:
        _identity(user_id, draft.draft_id)
        payload = json.dumps(draft.model_dump(mode="json"), sort_keys=True,
                             ensure_ascii=False, allow_nan=False)
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO plan_drafts (
                    user_id, draft_id, created_at, kind, based_on_plan_id, draft_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, draft_id) DO UPDATE SET draft_json=excluded.draft_json
                """,
                (user_id, draft.draft_id, _iso(draft.created_at), draft.kind,
                 draft.based_on_plan_id, payload),
            )

    def get_draft(self, user_id: str, draft_id: str) -> StoredPlanDraft | None:
        _identity(user_id, draft_id)
        with self.database.connection() as connection:
            return self._draft(connection, user_id, draft_id)

    def take_draft(self, user_id: str, draft_id: str) -> StoredPlanDraft | None:
        """Read and delete in one transaction, so two activations cannot share it."""
        _identity(user_id, draft_id)
        with self.database.transaction() as connection:
            draft = self._draft(connection, user_id, draft_id)
            if draft is not None:
                connection.execute(
                    "DELETE FROM plan_drafts WHERE user_id=? AND draft_id=?",
                    (user_id, draft_id))
            return draft

    # ------------------------------------------------------------- confirmation

    def activate(
        self,
        user_id: str,
        *,
        task_id: str,
        expected_version: int,
        expected_head_revision: int,
        candidate_digest: str,
        operation_key: str,
        verify: Verifier,
    ) -> PlanActivationReceipt:
        _identity(user_id, task_id, operation_key, candidate_digest)
        _positive_int(expected_version, "expected_version")
        _positive_int(expected_head_revision, "expected_head_revision")
        fingerprint = _fingerprint({
            "op": "activate", "owner": user_id, "task_id": task_id,
            "version": expected_version, "head_revision": expected_head_revision,
            "candidate_digest": candidate_digest,
        })
        with self.database.transaction() as connection:
            replayed = self._replay_activation(connection, user_id, operation_key, fingerprint)
            if replayed is not None:
                return replayed

            task = self._task_row(connection, user_id, task_id)
            now = self.clock()
            if task["state"] not in TERMINAL_STATES and _parse(task["expires_at"]) <= now:
                # An expired task is refused before its candidate is even looked
                # at: the answer is about the task, not about the plan.
                raise _task_error("TASK_EXPIRED")
            if task["version"] != expected_version:
                raise _task_error("TASK_VERSION_CONFLICT")
            if task["state"] != "awaiting_confirmation":
                raise _task_error("STATE_TRANSITION")
            if (task["candidate_expires_at"] is None
                    or _parse(task["candidate_expires_at"]) <= now):
                raise _plan_error("CANDIDATE_EXPIRED")

            head = self._head(connection, user_id)
            if (head is None or head.revision != expected_head_revision
                    or head.plan_id != task["base_plan_id"]):
                # Either the head moved since the user looked, or the task was
                # started from a plan that is no longer the head. Both mean the
                # candidate was reviewed against a base that is no longer current.
                raise _plan_error("PLAN_BASE_STALE")
            if task["candidate_digest"] != candidate_digest:
                raise _plan_error("CANDIDATE_DIGEST_MISMATCH")

            submission = self._passed_submission(connection, task_id, candidate_digest)
            document = json.loads(submission["candidate_json"])
            base = self._plan(connection, user_id, task["base_plan_id"])
            if base is None:
                raise _plan_error("PLAN_BASE_STALE")
            self._require_granted_change(connection, task_id, base, document)

            activated = verify(ActivationContext(
                user_id=user_id,
                task_id=task_id,
                base_plan_id=task["base_plan_id"],
                base_head_revision=task["base_head_revision"],
                constraints=json.loads(task["constraints_json"]),
                reviewed_digest=task["reviewed_digest"],
                candidate_id=submission["candidate_id"],
                candidate_digest=candidate_digest,
                candidate_plan=document,
                head=head,
                base_plan=base,
                constraints_at_write=self._constraints_at_write(connection, user_id),
            ))
            if not isinstance(activated, dict) or not activated:
                # A verifier that returns nothing has not produced a plan. Storing
                # the unverified candidate instead would make the check decorative.
                raise _plan_error("CANDIDATE_DOCUMENT_MISSING")

            plan = StoredPlan(
                plan_id=f"plan-{self._ids()}",
                activated_at=now,
                kind="agent_adjusted",
                based_on_plan_id=task["base_plan_id"],
                plan=activated,
            )
            self._insert_plan(connection, user_id, plan, now)
            self._advance_head(connection, user_id, plan.plan_id, head.revision + 1, now)
            self._mark_activated(connection, user_id, task_id, expected_version, now)
            receipt = PlanActivationReceipt(
                plan_id=plan.plan_id,
                head_revision=head.revision + 1,
                activated_at=now,
                kind="agent_adjusted",
                based_on_plan_id=task["base_plan_id"],
            )
            self._store_activation_receipt(connection, user_id, operation_key, task_id,
                                           fingerprint, receipt, now)
            return receipt

    # ------------------------------------------------------------------- import

    def import_history(self, user_id: str, plans, drafts=(), *,
                       head: PlanHead | None = None) -> dict[str, int]:
        """Copy a directory's history in, and establish its head.

        One transaction per owner rather than one for the whole directory: a
        large import would otherwise hold the write lock for its entire length.
        The import is safe to repeat because identical rows are no-ops, so a run
        that stopped halfway is repaired by running it again -- and the factory
        still refuses ``sqlite`` mode until the completion record exists, so a
        partial import is never served.

        The head is passed in, not derived from ``plans``: the importer computes
        it with ``legacy_head`` over *everything* the directory had, including
        plans this call found already present.
        """
        _identity(user_id)
        counts = {"plans": 0, "drafts": 0}
        with self.database.transaction() as connection:
            now = self.clock()
            for plan in plans:
                if self._insert_plan(connection, user_id, plan, now):
                    counts["plans"] += 1
            for draft in drafts:
                connection.execute(
                    """
                    INSERT INTO plan_drafts (
                        user_id, draft_id, created_at, kind, based_on_plan_id, draft_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, draft_id) DO NOTHING
                    """,
                    (user_id, draft.draft_id, _iso(draft.created_at), draft.kind,
                     draft.based_on_plan_id,
                     json.dumps(draft.model_dump(mode="json"), sort_keys=True,
                                ensure_ascii=False, allow_nan=False)),
                )
                counts["drafts"] += connection.execute(
                    "SELECT changes() AS changed").fetchone()["changed"]
            if head is not None:
                self._establish_head(connection, user_id, head)
        return counts

    # ---------------------------------------------------------------- lifecycle

    def delete_user_data(self, user_id: str) -> dict[str, int]:
        """Remove one owner's plans. Heads go first: they reference the history."""
        _identity(user_id)
        counts: dict[str, int] = {}
        with self.database.transaction() as connection:
            for table in ("plan_heads", "plans", "plan_drafts", "plan_activation_receipts"):
                counts[table] = connection.execute(
                    f"DELETE FROM {table} WHERE user_id=?", (user_id,)).rowcount
        return counts

    # ---------------------------------------------------------------- internals

    def _insert_plan(self, connection, user_id: str, plan: StoredPlan,
                     now: datetime) -> bool:
        """Insert one history row. Returns False when the identical row was there.

        ``content_digest`` is what makes the two cases distinguishable: the same
        id with the same bytes is a replay, and the same id with different bytes
        would replace an answer the user was already given.
        """
        document = plan.plan.model_dump(mode="json")
        payload = json.dumps(document, sort_keys=True, ensure_ascii=False, allow_nan=False)
        digest = _content_digest(document)
        existing = connection.execute(
            "SELECT content_digest FROM plans WHERE user_id=? AND plan_id=?",
            (user_id, plan.plan_id),
        ).fetchone()
        if existing is not None:
            if existing["content_digest"] != digest:
                raise _plan_error("PLAN_HISTORY_CONFLICT")
            return False
        connection.execute(
            """
            INSERT INTO plans (
                user_id, plan_id, activated_at, kind, based_on_plan_id,
                plan_json, content_digest, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, plan.plan_id, _iso(plan.activated_at), plan.kind,
             plan.based_on_plan_id, payload, digest, _iso(now)),
        )
        return True

    def _advance_head(self, connection, user_id: str, plan_id: str, revision: int,
                      now: datetime) -> None:
        """Move the head to ``revision``, refusing any other starting point.

        ``BEGIN IMMEDIATE`` already serialises writers, so within one transaction
        the row read a moment ago is still the row being written. The
        ``WHERE revision`` clause states that dependency in the statement itself:
        if this block ever stops holding the write lock for its whole length, the
        update fails loudly instead of overwriting a newer head.
        """
        current = self._head(connection, user_id)
        if current is None:
            connection.execute(
                "INSERT INTO plan_heads (user_id, plan_id, revision, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (user_id, plan_id, revision, _iso(now)),
            )
            return
        if revision != current.revision + 1:
            raise _plan_error("PLAN_BASE_STALE")
        cursor = connection.execute(
            "UPDATE plan_heads SET plan_id=?, revision=?, updated_at=? "
            "WHERE user_id=? AND revision=?",
            (plan_id, revision, _iso(now), user_id, current.revision),
        )
        if cursor.rowcount != 1:
            raise _plan_error("PLAN_BASE_STALE")

    def _mark_activated(self, connection, user_id: str, task_id: str,
                        expected_version: int, now: datetime) -> None:
        cursor = connection.execute(
            "UPDATE plan_adjustment_sessions "
            "SET state='activated', version=version+1, updated_at=? "
            "WHERE task_id=? AND user_id=? AND version=?",
            (_iso(now), task_id, user_id, expected_version),
        )
        if cursor.rowcount != 1:
            raise _task_error("TASK_VERSION_CONFLICT")

    def _store_activation_receipt(self, connection, user_id: str, operation_key: str,
                                  task_id: str, fingerprint: str,
                                  receipt: PlanActivationReceipt, now: datetime) -> None:
        connection.execute(
            """
            INSERT INTO plan_activation_receipts (
                user_id, operation_key, task_id, request_fingerprint,
                plan_id, head_revision, response_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, operation_key, task_id, fingerprint, receipt.plan_id,
             receipt.head_revision,
             json.dumps(receipt.model_dump(mode="json"), sort_keys=True, ensure_ascii=False),
             _iso(now)),
        )

    def _replay_activation(self, connection, user_id: str, operation_key: str,
                           fingerprint: str) -> PlanActivationReceipt | None:
        stored = connection.execute(
            "SELECT * FROM plan_activation_receipts WHERE user_id=? AND operation_key=?",
            (user_id, operation_key),
        ).fetchone()
        if stored is None:
            return None
        if stored["request_fingerprint"] != fingerprint:
            raise _task_error("IDEMPOTENCY_CONFLICT")
        receipt = PlanActivationReceipt.model_validate_json(stored["response_json"])
        return receipt.model_copy(update={"replayed": True})

    def _task_row(self, connection, user_id: str, task_id: str):
        row = connection.execute(
            "SELECT * FROM plan_adjustment_sessions WHERE task_id=? AND user_id=?",
            (task_id, user_id),
        ).fetchone()
        if row is None:
            # A task that belongs to somebody else is indistinguishable from one
            # that does not exist.
            raise _task_error("TASK_NOT_FOUND")
        return row

    def _passed_submission(self, connection, task_id: str, candidate_digest: str):
        row = connection.execute(
            "SELECT candidate_id, bundle_digest, candidate_json FROM plan_candidate_submissions "
            "WHERE task_id=? AND bundle_digest=? AND passed=1 AND candidate_json IS NOT NULL "
            "ORDER BY round_index DESC LIMIT 1",
            (task_id, candidate_digest),
        ).fetchone()
        if row is None:
            # A candidate that never passed has no document to activate. The
            # caller is told the document is missing rather than being handed the
            # task's own claim that a candidate exists.
            raise _plan_error("CANDIDATE_DOCUMENT_MISSING")
        return row

    def _change_domains(self, connection, task_id: str) -> frozenset[str]:
        rows = connection.execute(
            "SELECT domain FROM plan_task_permissions WHERE task_id=? AND can_change=1",
            (task_id,),
        ).fetchall()
        return frozenset(row["domain"] for row in rows)

    def _require_granted_change(self, connection, task_id: str, base: StoredPlan,
                                document: Mapping[str, Any]) -> None:
        """Every domain the candidate actually changed must have been granted.

        Submission already refused out-of-scope patches, so this is the second
        reader of the same rule. It exists because activation is the last place
        where a stored document could disagree with the grant it was produced
        under, and "the check ran earlier" is not evidence at write time.
        """
        from backend.agent.plan_adjustment.validation import domain_digests

        granted = self._change_domains(connection, task_id)
        if not granted:
            raise _plan_error("CHANGE_DOMAIN_NOT_AUTHORIZED")
        before = dict(domain_digests(base.plan.model_dump(mode="json")))
        after = dict(domain_digests(dict(document)))
        changed = {domain for domain, value in after.items() if before.get(domain) != value}
        if changed - granted:
            raise _plan_error("CHANGE_DOMAIN_NOT_AUTHORIZED")

    def _establish_head(self, connection, user_id: str, head: PlanHead) -> bool:
        """Write the head an import computed, and never move it backwards.

        A directory whose plans are all imported has ``revision = len(plans)``,
        which is the same counter a sequence of activations would have produced --
        so re-running the import after real activations lands on the same head.
        When the database is *ahead* of the directory (plans were activated after
        the import), the directory is the stale side and the head is left alone.
        Refusing instead would make "import an old backup on top" impossible,
        which is a legitimate way to recover a missing plan.
        """
        current = self._head(connection, user_id)
        if current is not None and current.revision >= head.revision:
            return False
        connection.execute(
            "INSERT INTO plan_heads (user_id, plan_id, revision, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "plan_id=excluded.plan_id, revision=excluded.revision, "
            "updated_at=excluded.updated_at",
            (user_id, head.plan_id, head.revision, _iso(head.updated_at)),
        )
        return True

    def _constraints_at_write(self, connection, user_id: str):
        """The versioned constraint snapshot, on this transaction's connection."""
        if self.constraints_reader is None:
            return None
        return self.constraints_reader(connection, user_id)

    def _head(self, connection, user_id: str) -> PlanHead | None:
        row = connection.execute(
            "SELECT plan_id, revision, updated_at FROM plan_heads WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        return PlanHead(plan_id=row["plan_id"], revision=row["revision"],
                        updated_at=_parse(row["updated_at"]))

    def _plan(self, connection, user_id: str, plan_id: str) -> StoredPlan | None:
        row = connection.execute(
            "SELECT * FROM plans WHERE user_id=? AND plan_id=?", (user_id, plan_id),
        ).fetchone()
        return None if row is None else self._plan_from_row(row)

    def _draft(self, connection, user_id: str, draft_id: str) -> StoredPlanDraft | None:
        row = connection.execute(
            "SELECT * FROM plan_drafts WHERE user_id=? AND draft_id=?", (user_id, draft_id),
        ).fetchone()
        if row is None:
            return None
        return StoredPlanDraft.model_validate(json.loads(row["draft_json"]))

    @staticmethod
    def _plan_from_row(row) -> StoredPlan:
        return StoredPlan(
            plan_id=row["plan_id"],
            activated_at=_parse(row["activated_at"]),
            kind=row["kind"],
            based_on_plan_id=row["based_on_plan_id"],
            plan=json.loads(row["plan_json"]),
        )
