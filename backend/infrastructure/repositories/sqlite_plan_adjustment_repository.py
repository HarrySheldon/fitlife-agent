"""SQLite plan tasks: compare-and-swap versions, claimed rounds, replay receipts.

The repository stores decisions that trusted code already made. It never builds a
model, never interprets user text and never decides whether a patch is sensible.

Three invariants are enforced here rather than in the caller, because a caller
that forgets them produces silent data loss:

* **version** -- every mutation compares the expected version and writes
  ``version + 1`` in one transaction, so a stale writer loses instead of merging;
* **rounds** -- a repair round is claimed by the reservation, before the next
  revision call. A model that never answers still costs the round;
* **replay** -- the receipt is matched before the version check, so a client
  retrying with the version it originally used gets its own answer back.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Mapping
from uuid import uuid4

from backend.application.ports.plan_adjustment_repository import (
    REPAIR_ROUND_LIMIT,
    REVIEW_CERTIFICATE_PREFIX,
    TASK_STATES,
    TERMINAL_STATES,
    CandidateRecord,
    TaskSnapshot,
)
from backend.infrastructure.sqlite.database import SQLiteDatabase

CREATE_SCOPE = "task_create"

# The only constraint fields a task may ask the user to fill. Everything else is
# either derived from trusted storage or not the user's to answer.
ANSWERABLE_CONSTRAINTS = frozenset({
    "allergies_or_restrictions", "action_restrictions", "available_equipment",
    "forbidden_exercises", "session_minutes",
})

# Where a task may go next. Terminal states go nowhere: an activated task is
# history, and a cancelled or expired one is closed.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "collecting": frozenset({"awaiting_scope_permission", "generating", "cancelled", "expired"}),
    "awaiting_scope_permission": frozenset({"collecting", "generating", "cancelled", "expired"}),
    "generating": frozenset({"awaiting_confirmation", "repairing", "awaiting_user_decision",
                             "cancelled", "expired"}),
    "repairing": frozenset({"awaiting_confirmation", "awaiting_user_decision", "cancelled", "expired"}),
    "awaiting_confirmation": frozenset({"activated", "generating", "repairing",
                                        "awaiting_user_decision", "cancelled", "expired"}),
    "awaiting_user_decision": frozenset({"generating", "repairing", "cancelled", "expired"}),
    "activated": frozenset(),
    "cancelled": frozenset(),
    "expired": frozenset(),
}

# A submission is only meaningful while a candidate could still be produced or
# repaired. Anywhere else it is a state conflict, not a validation failure.
_SUBMITTABLE = frozenset({"generating", "repairing", "awaiting_user_decision"})


def _task_error(code: str):
    from backend.agent.tasks.contracts import task_error
    return task_error(code)


def _identity(*values: str) -> None:
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError("PLAN_TASK_IDENTITY_REQUIRED")


def _positive_int(value: int, name: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"PLAN_TASK_FIELD_INVALID:{name}")


def _grant(read_domains, change_domains) -> None:
    for value in (read_domains, change_domains):
        if not isinstance(value, frozenset):
            raise ValueError("TRUSTED_DOMAIN_SNAPSHOT_REQUIRED")
        if any(domain not in {"training", "diet"} for domain in value):
            raise ValueError("PLAN_TASK_FIELD_INVALID:domain")
    if not read_domains:
        raise ValueError("PLAN_TASK_FIELD_INVALID:read_domains")
    if not change_domains <= read_domains:
        raise ValueError("CHANGE_DOMAIN_NOT_READABLE")


def _fingerprint(payload) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _payload(snapshot: TaskSnapshot) -> dict:
    return {
        "task_id": snapshot.task_id,
        "version": snapshot.version,
        "state": snapshot.state,
        "base_plan_id": snapshot.base_plan_id,
        "base_head_revision": snapshot.base_head_revision,
        "read_domains": sorted(snapshot.read_domains),
        "change_domains": sorted(snapshot.change_domains),
        "constraint_digest": snapshot.constraint_digest,
        "candidate_id": snapshot.candidate_id,
        "candidate_digest": snapshot.candidate_digest,
        "repair_rounds": snapshot.repair_rounds,
        "active_round_id": snapshot.active_round_id,
        "operation_id": snapshot.operation_id,
        "expires_at": _iso(snapshot.expires_at),
        "candidate_expires_at": _iso(snapshot.candidate_expires_at) if snapshot.candidate_expires_at else None,
    }


class SQLitePlanAdjustmentRepository:
    def __init__(self, database: SQLiteDatabase, *, clock=None, ids=None,
                 task_ttl_days: int | None = None, candidate_ttl_minutes: int | None = None):
        self.database = database
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._ids = ids or (lambda: uuid4().hex)
        if task_ttl_days is None or candidate_ttl_minutes is None:
            from backend.config import get_settings
            settings = get_settings()
            task_ttl_days = settings.plan_adjustment_task_ttl_days if task_ttl_days is None else task_ttl_days
            candidate_ttl_minutes = (settings.plan_candidate_ttl_minutes
                                     if candidate_ttl_minutes is None else candidate_ttl_minutes)
        _positive_int(task_ttl_days, "task_ttl_days")
        _positive_int(candidate_ttl_minutes, "candidate_ttl_minutes")
        self.task_ttl = timedelta(days=task_ttl_days)
        self.candidate_ttl = timedelta(minutes=candidate_ttl_minutes)

    # ---------------------------------------------------------------- creation

    def create_task(self, owner, *, base_plan_id, base_head_revision, read_domains,
                    change_domains, constraints, key) -> TaskSnapshot:
        _identity(owner, base_plan_id, key)
        _positive_int(base_head_revision, "base_head_revision")
        _grant(read_domains, change_domains)
        if not isinstance(constraints, dict):
            raise ValueError("PLAN_TASK_FIELD_INVALID:constraints")
        fingerprint = _fingerprint({
            "op": "create", "owner": owner, "base_plan_id": base_plan_id,
            "base_head_revision": base_head_revision,
            "read_domains": sorted(read_domains), "change_domains": sorted(change_domains),
            "constraints": constraints,
        })
        with self.database.transaction() as connection:
            stored = self._receipt(connection, owner, CREATE_SCOPE, key)
            if stored is not None:
                if stored["request_fingerprint"] != fingerprint:
                    raise _task_error("IDEMPOTENCY_CONFLICT")
                return self._snapshot(connection, owner, stored["task_id"])
            now = self.clock()
            task_id = self._ids()
            connection.execute(
                """
                INSERT INTO plan_adjustment_sessions (
                    task_id, user_id, version, state, base_plan_id, base_head_revision,
                    constraint_digest, constraints_json, repair_rounds, expires_at,
                    created_at, updated_at
                ) VALUES (?, ?, 1, 'collecting', ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (task_id, owner, base_plan_id, base_head_revision,
                 _fingerprint(constraints), json.dumps(constraints, sort_keys=True, ensure_ascii=False),
                 _iso(now + self.task_ttl), _iso(now), _iso(now)),
            )
            self._replace_permissions(connection, task_id, read_domains, change_domains)
            snapshot = self._snapshot(connection, owner, task_id)
            self._store_receipt(connection, owner, CREATE_SCOPE, key, task_id, fingerprint, snapshot, now)
            return snapshot

    # ------------------------------------------------------------------- reads

    def get(self, owner, task_id) -> TaskSnapshot:
        _identity(owner, task_id)
        with self.database.transaction() as connection:
            snapshot = self._snapshot(connection, owner, task_id)
            return self._expire(connection, snapshot)

    def constraints(self, owner, task_id) -> dict:
        """The hard constraints frozen when the task was created.

        Validation must use this snapshot, not a fresh read of the user's
        profile: a restriction added after the candidate was produced would
        otherwise be checked against a plan the user never saw.
        """
        _identity(owner, task_id)
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT constraints_json FROM plan_adjustment_sessions WHERE task_id=? AND user_id=?",
                (task_id, owner),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            return json.loads(row["constraints_json"])

    # -------------------------------------------------------------- mutations

    def grant(self, owner, task_id, expected_version, read_domains, change_domains, key) -> TaskSnapshot:
        _identity(owner, task_id, key)
        _positive_int(expected_version, "expected_version")
        _grant(read_domains, change_domains)
        fingerprint = _fingerprint({
            "op": "grant", "owner": owner, "task_id": task_id, "version": expected_version,
            "read_domains": sorted(read_domains), "change_domains": sorted(change_domains),
        })
        with self.database.transaction() as connection:
            replayed = self._replay(connection, owner, task_id, key, fingerprint)
            if replayed is not None:
                return replayed
            snapshot = self._writable(connection, owner, task_id, expected_version)
            if snapshot.state not in {"collecting", "awaiting_scope_permission"}:
                # Widening or narrowing the scope after generation started would
                # silently reuse a candidate produced under different limits. The
                # user may start a linked task instead; the model may not.
                raise _task_error("REQUIRES_NEW_TASK")
            self._replace_permissions(connection, task_id, read_domains, change_domains)
            updated = self._write(connection, owner, snapshot, state="generating")
            self._store_receipt(connection, owner, task_id, key, task_id, fingerprint, updated, self.clock())
            return updated

    def reserve_repair_round(self, owner, task_id, expected_version, operation_id,
                             failed_domains) -> TaskSnapshot:
        _identity(owner, task_id, operation_id)
        _positive_int(expected_version, "expected_version")
        if not isinstance(failed_domains, frozenset):
            raise ValueError("TRUSTED_DOMAIN_SNAPSHOT_REQUIRED")
        if any(domain not in {"training", "diet"} for domain in failed_domains):
            raise ValueError("PLAN_TASK_FIELD_INVALID:domain")
        fingerprint = _fingerprint({
            "op": "reserve", "owner": owner, "task_id": task_id, "version": expected_version,
            "operation_id": operation_id, "failed_domains": sorted(failed_domains),
        })
        with self.database.transaction() as connection:
            replayed = self._replay(connection, owner, task_id, operation_id, fingerprint)
            if replayed is not None:
                return replayed
            snapshot = self._writable(connection, owner, task_id, expected_version)
            if snapshot.repair_rounds >= REPAIR_ROUND_LIMIT:
                raise _task_error("REPAIR_LIMIT")
            if snapshot.active_round_id is not None:
                # One open round at a time: the next one is only claimable after
                # the current round accepted its bundle.
                raise _task_error("REPAIR_ROUND_ACTIVE")
            if snapshot.state not in _SUBMITTABLE:
                raise _task_error("STATE_TRANSITION")
            index = snapshot.repair_rounds + 1
            round_id = self._ids()
            now = self.clock()
            connection.execute(
                """
                INSERT INTO plan_repair_rounds (
                    task_id, round_index, round_id, operation_id, failed_domains_json,
                    state, created_at
                ) VALUES (?, ?, ?, ?, ?, 'reserved', ?)
                """,
                (task_id, index, round_id, operation_id,
                 json.dumps(sorted(failed_domains), ensure_ascii=False), _iso(now)),
            )
            updated = self._write(connection, owner, snapshot, state="repairing",
                                  repair_rounds=index, active_round_id=round_id,
                                  operation_id=operation_id)
            self._store_receipt(connection, owner, task_id, operation_id, task_id, fingerprint, updated, now)
            return updated

    def submit_bundle(self, owner, task_id, expected_version, operation_id, bundle, verdict,
                      candidate=None, *, review_pending=False) -> TaskSnapshot:
        _identity(owner, task_id, operation_id)
        _positive_int(expected_version, "expected_version")
        digest = bundle.digest()
        fingerprint = _fingerprint({
            "op": "submit", "owner": owner, "task_id": task_id, "version": expected_version,
            "operation_id": operation_id, "bundle": digest,
        })
        document = None if candidate is None else json.dumps(
            candidate, sort_keys=True, ensure_ascii=False, allow_nan=False)
        with self.database.transaction() as connection:
            replayed = self._replay(connection, owner, task_id, operation_id, fingerprint)
            if replayed is not None:
                return replayed
            snapshot = self._writable(connection, owner, task_id, expected_version)
            if snapshot.state not in _SUBMITTABLE:
                raise _task_error("STATE_TRANSITION")
            round_index = self._round_index(connection, snapshot)
            existing = connection.execute(
                "SELECT bundle_digest FROM plan_candidate_submissions WHERE task_id=? AND round_index=?",
                (task_id, round_index),
            ).fetchone()
            if existing is not None:
                if existing["bundle_digest"] != digest:
                    raise _task_error("IDEMPOTENCY_CONFLICT")
                return self._snapshot(connection, owner, task_id)
            now = self.clock()
            connection.execute(
                """
                INSERT INTO plan_candidate_submissions (
                    task_id, round_index, candidate_id, bundle_digest, dependency_digest,
                    verdict_json, passed, created_at, candidate_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, round_index, verdict.candidate_id, digest, verdict.dependency_digest,
                 json.dumps(verdict.model_dump(mode="json"), sort_keys=True, ensure_ascii=False),
                 int(bool(verdict.passed)), _iso(now), document),
            )
            if snapshot.active_round_id is not None:
                connection.execute(
                    "UPDATE plan_repair_rounds SET state='accepted' WHERE task_id=? AND round_id=?",
                    (task_id, snapshot.active_round_id),
                )
            if verdict.passed:
                updated = self._write(
                    connection, owner, snapshot,
                    state='awaiting_user_decision' if review_pending else 'awaiting_confirmation', active_round_id=None,
                    candidate_id=verdict.candidate_id, candidate_digest=verdict.digest,
                    candidate_expires_at=_iso(now + self.candidate_ttl),
                )
            else:
                # A rejected candidate still consumed its round.
                updated = self._write(connection, owner, snapshot, state="repairing",
                                      active_round_id=None, candidate_id=None,
                                      candidate_digest=None, candidate_expires_at=None)
            self._store_receipt(connection, owner, task_id, operation_id, task_id, fingerprint, updated, now)
            return updated

    # ------------------------------------------------------------ projections

    def latest_candidate(self, owner, task_id) -> CandidateRecord | None:
        """The newest submission, whether or not it produced a merged plan.

        ``plan`` is ``None`` when the bundle could not be applied (stale value,
        out-of-scope path). The record still matters -- it says what the model
        tried and why it was refused -- but the next round edits the last
        document that exists, because a bundle that changed nothing is not a base.
        """
        _identity(owner, task_id)
        with self.database.transaction() as connection:
            self._snapshot(connection, owner, task_id)
            row = connection.execute(
                """
                SELECT round_index, candidate_id, bundle_digest, passed, verdict_json, candidate_json
                FROM plan_candidate_submissions
                WHERE task_id=?
                ORDER BY round_index DESC LIMIT 1
                """,
                (task_id,),
            ).fetchone()
            if row is None:
                return None
            verdict = json.loads(row["verdict_json"])
            return CandidateRecord(
                round_index=row["round_index"], candidate_id=row["candidate_id"],
                digest=row["bundle_digest"], passed=bool(row["passed"]),
                failed_domains=frozenset(verdict.get("failed_domains") or ()),
                domain_digests={str(domain): str(digest)
                                for domain, digest in verdict.get("domain_digests") or ()},
                plan=json.loads(row["candidate_json"]) if row["candidate_json"] else None,
                violations=tuple(dict(item) for item in verdict.get("violations") or ()),
            )

    def round_scope(self, owner, task_id) -> frozenset[str] | None:
        """The domains the open round may touch, as recorded at reservation.

        The reservation is the reason a domain may be revised: it was written
        before the model was called, so a later bundle cannot invent a reason.
        """
        _identity(owner, task_id)
        with self.database.transaction() as connection:
            snapshot = self._snapshot(connection, owner, task_id)
            if snapshot.active_round_id is None:
                return None
            row = connection.execute(
                "SELECT failed_domains_json FROM plan_repair_rounds WHERE task_id=? AND round_id=?",
                (task_id, snapshot.active_round_id),
            ).fetchone()
            if row is None:
                raise _task_error("STATE_TRANSITION")
            return frozenset(json.loads(row["failed_domains_json"]))

    # --------------------------------------------------------------- answers

    def answer_constraints(self, owner, task_id, expected_version, answers, key) -> TaskSnapshot:
        """Fill the missing hard constraints a task asked about.

        Answers are merged into the frozen snapshot and the digest moves with
        them, so a later validation cannot tell itself the task still had the
        unknowns it was created with.
        """
        _identity(owner, task_id, key)
        _positive_int(expected_version, "expected_version")
        if not isinstance(answers, Mapping) or not answers:
            raise ValueError("PLAN_ANSWER_EMPTY")
        if set(answers) - ANSWERABLE_CONSTRAINTS:
            raise ValueError("PLAN_ANSWER_NOT_ALLOWED")
        fingerprint = _fingerprint({
            "op": "answer", "owner": owner, "task_id": task_id,
            "version": expected_version, "answers": dict(answers),
        })
        with self.database.transaction() as connection:
            replayed = self._replay(connection, owner, task_id, key, fingerprint)
            if replayed is not None:
                return replayed
            snapshot = self._writable(connection, owner, task_id, expected_version)
            if snapshot.state != "awaiting_user_decision":
                raise _task_error("STATE_TRANSITION")
            row = connection.execute(
                "SELECT constraints_json FROM plan_adjustment_sessions WHERE task_id=? AND user_id=?",
                (task_id, owner),
            ).fetchone()
            merged = json.loads(row["constraints_json"])
            merged.update(dict(answers))
            from backend.domain.plan_adjustment import PlanConstraints
            validated = PlanConstraints.model_validate(merged).model_dump(mode="json")
            now = self.clock()
            updated = self._write(
                connection, owner, snapshot, state="generating",
                constraints_json=json.dumps(validated, sort_keys=True, ensure_ascii=False),
                constraint_digest=_fingerprint(validated),
            )
            self._store_receipt(connection, owner, task_id, key, task_id, fingerprint, updated, now)
            return updated

    def transition(self, owner, task_id, expected_version, state, key) -> TaskSnapshot:
        _identity(owner, task_id, key)
        _positive_int(expected_version, "expected_version")
        if state not in TASK_STATES:
            raise ValueError("STATE_TRANSITION")
        fingerprint = _fingerprint({"op": "transition", "owner": owner, "task_id": task_id,
                                    "version": expected_version, "state": state})
        with self.database.transaction() as connection:
            replayed = self._replay(connection, owner, task_id, key, fingerprint)
            if replayed is not None:
                return replayed
            snapshot = self._writable(connection, owner, task_id, expected_version)
            if state not in ALLOWED_TRANSITIONS[snapshot.state]:
                raise _task_error("STATE_TRANSITION")
            updated = self._write(connection, owner, snapshot, state=state)
            self._store_receipt(connection, owner, task_id, key, task_id, fingerprint, updated, self.clock())
            return updated

    # ------------------------------------------------------------- lifecycle

    def record_review(self, owner, task_id, digest) -> None:
        """Annotate the current candidate as reviewed. Not a state transition.

        The version does not move: nothing a caller can observe changes, and
        spending a version would turn "a review finished" into "the task moved",
        which would invalidate a confirmation the user was about to send. The
        digest in the WHERE clause is what keeps the annotation attached to the
        candidate it describes.
        """
        _identity(owner, task_id, digest)
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE plan_adjustment_sessions SET reviewed_digest=? "
                "WHERE task_id=? AND user_id=? AND candidate_digest=?",
                (REVIEW_CERTIFICATE_PREFIX + digest, task_id, owner, digest),
            )

    def finish_review(self, owner, task_id, digest, *, allowed, expected_version=None):
        with self.database.transaction() as connection:
            snapshot = self._snapshot(connection, owner, task_id)
            self._require_live_candidate(snapshot)
            if snapshot.state in TERMINAL_STATES or snapshot.candidate_digest != digest:
                raise _task_error('TASK_VERSION_CONFLICT')
            self._writable(connection, owner, task_id, snapshot.version)
            if expected_version is not None and snapshot.version != expected_version:
                raise _task_error('TASK_VERSION_CONFLICT')
            if snapshot.state != 'awaiting_user_decision':
                raise _task_error('STATE_TRANSITION')
            return self._write(connection, owner, snapshot,
                state='awaiting_confirmation' if allowed else 'awaiting_user_decision',
                reviewed_digest=REVIEW_CERTIFICATE_PREFIX + digest if allowed else None)

    def prepare_review(self, owner, task_id):
        with self.database.transaction() as connection:
            snapshot = self._snapshot(connection, owner, task_id)
            self._require_live_candidate(snapshot)
            row = connection.execute('SELECT reviewed_digest FROM plan_adjustment_sessions WHERE task_id=? AND user_id=?',
                                     (task_id, owner)).fetchone()
            if not snapshot.candidate_digest or row['reviewed_digest'] == REVIEW_CERTIFICATE_PREFIX + snapshot.candidate_digest:
                return False
            if snapshot.state in TERMINAL_STATES:
                raise _task_error('STATE_TRANSITION')
            self._writable(connection, owner, task_id, snapshot.version)
            if snapshot.state != 'awaiting_user_decision':
                self._write(connection, owner, snapshot, state='awaiting_user_decision')
            return True

    def _require_live_candidate(self, snapshot):
        if snapshot.candidate_expires_at is None or snapshot.candidate_expires_at <= self.clock():
            from backend.domain.errors import ApplicationError
            raise ApplicationError(code='CANDIDATE_EXPIRED', message='The candidate has expired.', status_code=409)

    def candidate_is_live(self, owner, task_id):
        snapshot = self.get(owner, task_id)
        return (snapshot.expires_at > self.clock() and snapshot.candidate_expires_at is not None
                and snapshot.candidate_expires_at > self.clock())

    def claim_execution(self, owner, task_id, version, key, instructions, *, reserve=True):
        """Claim before any provider work; a pending/failed attempt is never rerun."""
        scope = f'execute:{task_id}'
        fingerprint = _fingerprint({'version': version, 'instructions': instructions})
        with self.database.transaction() as connection:
            self._snapshot(connection, owner, task_id)
            row = self._receipt(connection, owner, scope, key)
            if row is not None:
                if row['request_fingerprint'] != fingerprint:
                    raise _task_error('IDEMPOTENCY_CONFLICT')
                response = json.loads(row['response_json'])
                if response['status'] != 'done':
                    from backend.domain.errors import ApplicationError
                    raise ApplicationError(code='PLAN_EXECUTION_PENDING',
                        message='Read the task before explicitly starting another attempt.', status_code=409)
                return response['result']
            if not reserve:
                return None
            self._writable(connection, owner, task_id, version)
            connection.execute('INSERT INTO plan_task_receipts '
                '(user_id,scope,operation_key,task_id,request_fingerprint,response_json,created_at) '
                'VALUES (?,?,?,?,?,?,?)',
                (owner, scope, key, task_id, fingerprint, '{"status":"pending"}', _iso(self.clock())))
        return None

    def list_tasks(self, owner):
        with self.database.connection() as connection:
            rows = connection.execute('SELECT task_id FROM plan_adjustment_sessions '
                'WHERE user_id=? AND expires_at>? ORDER BY updated_at DESC LIMIT 50',
                (owner, _iso(self.clock()))).fetchall()
        return [self.get(owner, row['task_id']) for row in rows]

    def export_user_data(self, owner, *, max_bytes):
        with self.database.connection() as connection:
            sessions = connection.execute('SELECT * FROM plan_adjustment_sessions WHERE user_id=? AND expires_at>?',
                (owner, _iso(self.clock()))).fetchall()
            payload = {'plan_adjustment_sessions': [dict(row) for row in sessions]}
            for table in ('plan_candidate_submissions', 'plan_repair_rounds', 'plan_task_permissions', 'plan_task_receipts'):
                payload[table] = [dict(row) for task in sessions for row in connection.execute(
                    f'SELECT * FROM {table} WHERE task_id=?', (task['task_id'],)).fetchall()]
        encoded = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        if len(encoded) > max_bytes:
            raise ValueError('Plan task export exceeds limit')
        return encoded

    def finish_execution(self, owner, task_id, key, result):
        with self.database.transaction() as connection:
            self._snapshot(connection, owner, task_id)
            connection.execute('UPDATE plan_task_receipts SET response_json=? '
                'WHERE user_id=? AND scope=? AND operation_key=?',
                (json.dumps({'status': 'done', 'result': result}, ensure_ascii=False),
                 owner, f'execute:{task_id}', key))

    def delete_user_data(self, owner) -> dict[str, int]:
        _identity(owner)
        counts: dict[str, int] = {}
        with self.database.transaction() as connection:
            task_ids = [row["task_id"] for row in connection.execute(
                "SELECT task_id FROM plan_adjustment_sessions WHERE user_id=?", (owner,)).fetchall()]
            for table in ("plan_candidate_submissions", "plan_repair_rounds", "plan_task_permissions"):
                counts[table] = sum(
                    connection.execute(f"DELETE FROM {table} WHERE task_id=?", (task_id,)).rowcount
                    for task_id in task_ids)
            counts["plan_adjustment_sessions"] = connection.execute(
                "DELETE FROM plan_adjustment_sessions WHERE user_id=?", (owner,)).rowcount
            counts["plan_task_receipts"] = connection.execute(
                "DELETE FROM plan_task_receipts WHERE user_id=?", (owner,)).rowcount
        return counts

    # -------------------------------------------------------------- internals

    def _snapshot(self, connection, owner, task_id) -> TaskSnapshot:
        row = connection.execute(
            "SELECT * FROM plan_adjustment_sessions WHERE task_id=? AND user_id=?",
            (task_id, owner),
        ).fetchone()
        if row is None:
            # A task that belongs to somebody else is indistinguishable from a
            # task that does not exist.
            raise KeyError(task_id)
        permissions = connection.execute(
            "SELECT domain, can_read, can_change FROM plan_task_permissions WHERE task_id=?",
            (task_id,),
        ).fetchall()
        return TaskSnapshot(
            task_id=row["task_id"],
            version=row["version"],
            state=row["state"],
            base_plan_id=row["base_plan_id"],
            base_head_revision=row["base_head_revision"],
            read_domains=frozenset(item["domain"] for item in permissions if item["can_read"]),
            change_domains=frozenset(item["domain"] for item in permissions if item["can_change"]),
            constraint_digest=row["constraint_digest"],
            candidate_id=row["candidate_id"],
            candidate_digest=row["candidate_digest"],
            repair_rounds=row["repair_rounds"],
            active_round_id=row["active_round_id"],
            operation_id=row["operation_id"],
            expires_at=_parse(row["expires_at"]),
            candidate_expires_at=_parse(row["candidate_expires_at"]) if row["candidate_expires_at"] else None,
        )

    def _writable(self, connection, owner, task_id, expected_version) -> TaskSnapshot:
        snapshot = self._snapshot(connection, owner, task_id)
        if snapshot.state == "expired" or (snapshot.state not in TERMINAL_STATES
                                           and snapshot.expires_at <= self.clock()):
            raise _task_error("TASK_EXPIRED")
        if snapshot.version != expected_version:
            raise _task_error("TASK_VERSION_CONFLICT")
        return snapshot

    def _expire(self, connection, snapshot: TaskSnapshot) -> TaskSnapshot:
        if snapshot.state in TERMINAL_STATES or snapshot.expires_at > self.clock():
            return snapshot
        connection.execute(
            "UPDATE plan_adjustment_sessions SET state='expired', updated_at=? WHERE task_id=? AND version=?",
            (_iso(self.clock()), snapshot.task_id, snapshot.version),
        )
        return replace(snapshot, state="expired")

    def _write(self, connection, owner, snapshot: TaskSnapshot, **columns) -> TaskSnapshot:
        values = {"state": columns.pop("state"), "version": snapshot.version + 1,
                  "updated_at": _iso(self.clock()), **columns}
        assignments = ", ".join(f"{name}=?" for name in values)
        cursor = connection.execute(
            f"UPDATE plan_adjustment_sessions SET {assignments} WHERE task_id=? AND version=?",
            (*values.values(), snapshot.task_id, snapshot.version),
        )
        if cursor.rowcount != 1:
            # The compare-and-swap guard: a concurrent writer already moved on.
            raise _task_error("TASK_VERSION_CONFLICT")
        return self._snapshot(connection, owner, snapshot.task_id)

    def _replace_permissions(self, connection, task_id, read_domains, change_domains) -> None:
        connection.execute("DELETE FROM plan_task_permissions WHERE task_id=?", (task_id,))
        for domain in sorted(read_domains | change_domains):
            connection.execute(
                "INSERT INTO plan_task_permissions (task_id, domain, can_read, can_change) VALUES (?, ?, ?, ?)",
                (task_id, domain, int(domain in read_domains), int(domain in change_domains)),
            )

    def _round_index(self, connection, snapshot: TaskSnapshot) -> int:
        if snapshot.active_round_id is not None:
            row = connection.execute(
                "SELECT round_index FROM plan_repair_rounds WHERE task_id=? AND round_id=?",
                (snapshot.task_id, snapshot.active_round_id),
            ).fetchone()
            if row is None:
                raise _task_error("STATE_TRANSITION")
            return row["round_index"]
        if snapshot.repair_rounds == 0 and snapshot.state == "generating":
            # The first candidate is not a repair and does not spend a round.
            return 0
        # A repair must claim its round before the revision call is made.
        raise _task_error("REPAIR_ROUND_ACTIVE")

    def _receipt(self, connection, owner, scope, key):
        return connection.execute(
            "SELECT * FROM plan_task_receipts WHERE user_id=? AND scope=? AND operation_key=?",
            (owner, scope, key),
        ).fetchone()

    def _replay(self, connection, owner, task_id, key, fingerprint) -> TaskSnapshot | None:
        stored = self._receipt(connection, owner, task_id, key)
        if stored is None:
            return None
        if stored["request_fingerprint"] != fingerprint:
            raise _task_error("IDEMPOTENCY_CONFLICT")
        # Same request, same answer: the stored response is what the caller
        # originally saw, even if the task has moved on since.
        return self._from_payload(json.loads(stored["response_json"]))

    @staticmethod
    def _from_payload(payload: dict) -> TaskSnapshot:
        return TaskSnapshot(
            task_id=payload["task_id"], version=payload["version"], state=payload["state"],
            base_plan_id=payload["base_plan_id"], base_head_revision=payload["base_head_revision"],
            read_domains=frozenset(payload["read_domains"]),
            change_domains=frozenset(payload["change_domains"]),
            constraint_digest=payload["constraint_digest"], candidate_id=payload["candidate_id"],
            candidate_digest=payload["candidate_digest"], repair_rounds=payload["repair_rounds"],
            active_round_id=payload["active_round_id"], operation_id=payload["operation_id"],
            expires_at=_parse(payload["expires_at"]),
            candidate_expires_at=(_parse(payload["candidate_expires_at"])
                                  if payload["candidate_expires_at"] else None),
        )

    def _store_receipt(self, connection, owner, scope, key, task_id, fingerprint,
                       snapshot: TaskSnapshot, now: datetime) -> None:
        connection.execute(
            """
            INSERT INTO plan_task_receipts (
                user_id, scope, operation_key, task_id, request_fingerprint, response_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (owner, scope, key, task_id, fingerprint,
             json.dumps(_payload(snapshot), sort_keys=True, ensure_ascii=False), _iso(now)),
        )
