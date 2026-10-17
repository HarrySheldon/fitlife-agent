"""Atomic food confirmation and durable, body-independent commit facts."""
from dataclasses import asdict, replace
import hashlib
import json
from types import SimpleNamespace

from backend.application.ports.smart_entry_repository import (
    ConfirmedEntryItems, EntryItemCommit, SmartEntryRepositoryError as Error,
)
from backend.domain.entry_resolution import catalog_signature, consumed_amount, resolve_item
from backend.domain.smart_entry import SmartEntryDomainError
from backend.domain.meals import MealDomainError
from backend.infrastructure.repositories.sqlite_daily_log import ensure_daily_log

OPERATION = 'entry_confirm_items'
MAX_RECEIPT_BYTES = 32 * 1024


def record_hash(connection, meal_id, item_id):
    row = connection.execute('SELECT * FROM meal_items WHERE id = ? AND meal_id = ?',
                             (item_id, meal_id)).fetchone()
    meal = connection.execute('SELECT * FROM meals WHERE id = ?', (meal_id,)).fetchone()
    if row is None or meal is None:
        return None
    return hashlib.sha256(json.dumps([dict(meal), dict(row)], sort_keys=True,
                                    ensure_ascii=False).encode()).hexdigest()


def _facts(connection, user, draft, selections):
    facts = []
    for item, revision in selections:
        row = connection.execute('SELECT * FROM entry_item_commits WHERE user_id=? AND draft_id=? AND item_id=? AND item_revision=?',
                                 (user, draft, item, revision)).fetchone()
        if row is not None:
            current = record_hash(connection, row['meal_id'], row['meal_item_id'])
            facts.append(EntryItemCommit(item, revision, row['meal_id'], row['meal_item_id'],
                         'deleted' if current is None else 'unchanged' if current == row['record_hash'] else 'changed'))
    return tuple(facts)


def _selection(value):
    if hasattr(value, 'model_dump'):
        value = value.model_dump()
    if not isinstance(value, dict) or set(value) != {'item_id', 'item_revision'}:
        raise Error('ENTRY_COMMAND_INVALID')
    if not isinstance(value['item_id'], str) or not value['item_id'].strip() or type(value['item_revision']) is not int or value['item_revision'] < 1:
        raise Error('ENTRY_COMMAND_INVALID')
    return value['item_id'], value['item_revision']


def _receipt(serialized):
    """Read only the closed, bounded minimal fact receipt, never a draft body."""
    try:
        if not isinstance(serialized, str) or len(serialized.encode('utf-8')) > MAX_RECEIPT_BYTES:
            raise ValueError
        data = json.loads(serialized)
        if not isinstance(data, dict) or set(data) != {'draft_id', 'fingerprint', 'commits', 'version'}:
            raise ValueError
        if not isinstance(data['draft_id'], str) or not data['draft_id'].strip():
            raise ValueError
        if (not isinstance(data['fingerprint'], str) or not data['fingerprint'].strip()
                or len(data['fingerprint']) > 200 or type(data['version']) is not int or data['version'] < 1):
            raise ValueError
        if not isinstance(data['commits'], list) or not 1 <= len(data['commits']) <= 100:
            raise ValueError
        identities = set()
        for fact in data['commits']:
            if not isinstance(fact, dict) or set(fact) != {'item_id', 'item_revision', 'meal_id', 'meal_item_id', 'record_state'}:
                raise ValueError
            identity = _selection({key: fact[key] for key in ('item_id', 'item_revision')})
            if identity in identities:
                raise ValueError
            identities.add(identity)
            if any(not isinstance(fact[key], str) or not fact[key].strip() for key in ('meal_id', 'meal_item_id')):
                raise ValueError
            if fact['record_state'] not in ('unchanged', 'changed', 'deleted'):
                raise ValueError
        return data
    except (ValueError, TypeError, KeyError, RecursionError, Error):
        raise Error('IDEMPOTENCY_RESPONSE_CORRUPT') from None


def confirm_items(repository, user, draft_id, *, expected_version, selections,
                  idempotency_key, request_fingerprint, timezone_name='UTC', accepted_estimates=()):
    from backend.infrastructure.repositories.sqlite_smart_entry_repository import (
        _draft, _require_draft, _payload_json, _timestamp, _validate_selected_candidates,
    )
    selected = tuple(sorted(set(_selection(value) for value in selections)))
    accepted = set(_selection(value) for value in accepted_estimates)
    if not selected or not accepted.issubset(selected) or type(expected_version) is not int or expected_version < 1:
        raise Error('ENTRY_COMMAND_INVALID')
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 200:
        raise Error('ENTRY_COMMAND_INVALID')
    if not isinstance(request_fingerprint, str) or not request_fingerprint.strip() or len(request_fingerprint) > 200:
        raise Error('ENTRY_COMMAND_INVALID')
    with repository.database.transaction() as connection:
        receipt = connection.execute('SELECT response_json FROM idempotency_keys WHERE user_id=? AND operation=? AND idempotency_key=?',
                                     (user, OPERATION, idempotency_key)).fetchone()
        if receipt:
            data = _receipt(receipt['response_json'])
            if data['fingerprint'] != request_fingerprint or data['draft_id'] != draft_id:
                raise Error('IDEMPOTENCY_KEY_REUSED')
            historical = tuple((value['item_id'], value['item_revision']) for value in data['commits'])
            facts = _facts(connection, user, draft_id, historical)
            if (historical != selected or len(facts) != len(historical)
                    or any((fact.meal_id, fact.meal_item_id) != (stored['meal_id'], stored['meal_item_id'])
                           for fact, stored in zip(facts, data['commits']))):
                raise Error('IDEMPOTENCY_RESPONSE_CORRUPT')
            return ConfirmedEntryItems(draft_id, facts, data['version'], True)
        now_value = repository._clock()
        row = _require_draft(connection, user, draft_id, expected_version=None, now=now_value)
        draft = _draft(row)
        if not draft.payload.interaction.active:
            raise Error('INTERACTION_NOT_ACTIVE')
        facts = _facts(connection, user, draft_id, selected)
        if len(facts) != len(selected) and draft.version != expected_version:
            raise Error('DRAFT_VERSION_CONFLICT')
        known = {(fact.item_id, fact.item_revision) for fact in facts}
        candidates = {candidate.id: candidate for candidate in draft.payload.candidates}
        items = {item.item_id: item for item in draft.payload.interaction.items}
        dependencies = {dep.item_id: dep for dep in draft.payload.interaction.dependencies}
        pending = []
        for item_id, revision in selected:
            if (item_id, revision) in known:
                continue
            item = items.get(item_id)
            candidate = candidates.get(item_id)
            if item is None or candidate is None or candidate.kind != 'food':
                raise Error('ITEM_NOT_FOUND')
            if item.revision != revision:
                raise Error('ITEM_REVISION_CONFLICT')
            if item.state != 'ready':
                raise Error('ITEM_NOT_READY')
            estimated = any(source == 'estimated' for source in item.sources.values()) or bool(item.values.get('is_estimate'))
            if estimated and (item_id, revision) not in accepted:
                raise Error('ESTIMATE_ACCEPTANCE_REQUIRED')
            food = None
            if candidate.selected_catalog_id:
                catalog = connection.execute('SELECT * FROM food_catalog WHERE id=? AND active=1 AND (owner_user_id IS NULL OR owner_user_id=?)',
                                             (candidate.selected_catalog_id, user)).fetchone()
                if catalog is None:
                    raise Error('SMART_ENTRY_CATALOG_NOT_VISIBLE')
                food = SimpleNamespace(**{**dict(catalog), 'active': bool(catalog['active'])})
                dep = dependencies.get(item_id)
                if dep is None or dep.catalog_id != food.id or dep.signature != catalog_signature(food):
                    raise Error('CATALOG_DEPENDENCY_CHANGED')
            try:
                resolved = resolve_item(item, food)
                if resolved.state != 'ready':
                    raise Error('ITEM_NOT_READY')
                values = {**resolved.values, 'amount': consumed_amount(item), 'is_estimate': estimated}
                candidate = replace(candidate, values=values, issues=(), assumptions=item.assumptions,
                                    agent_estimate_accepted=True,
                                    provenance={**candidate.provenance, 'field_sources': item.sources})
                _validate_selected_candidates((candidate,))
            except (SmartEntryDomainError, MealDomainError) as error:
                raise Error(error.code) from None
            pending.append((item, candidate))
        now = _timestamp(now_value)
        if pending:
            ensure_daily_log(connection, repository._id_factory, user, draft.payload.log_date, now, timezone_name)
            for item, candidate in pending:
                meal_id = repository._insert_meals(connection, user, draft.payload.log_date, (candidate,), now)[0]
                meal_item_id = connection.execute('SELECT id FROM meal_items WHERE meal_id=?', (meal_id,)).fetchone()['id']
                connection.execute('INSERT INTO entry_item_commits VALUES (?,?,?,?,?,?,?,?)',
                                   (user, draft_id, item.item_id, item.revision, meal_id, meal_item_id,
                                    record_hash(connection, meal_id, meal_item_id), now))
                items[item.item_id] = replace(item, state='saved')
            interaction = replace(draft.payload.interaction, items=tuple(items.values()),
                status='completed' if all(item.state in ('saved', 'discarded') for item in items.values())
                and not any(candidate.kind != 'food' for candidate in draft.payload.candidates) else 'partially_saved')
            payload = replace(draft.payload, interaction=interaction)
            connection.execute('UPDATE record_drafts SET payload_json=?, version=version+1, updated_at=? WHERE id=? AND user_id=?',
                               (_payload_json(payload), now, draft_id, user))
            connection.execute('UPDATE daily_logs SET planned_meal_count=MAX(planned_meal_count,(SELECT COUNT(*) FROM meals WHERE user_id=? AND log_date=?)),updated_at=? WHERE user_id=? AND log_date=?',
                               (user, draft.payload.log_date, now, user, draft.payload.log_date))
        result = ConfirmedEntryItems(draft_id, _facts(connection, user, draft_id, selected), draft.version + bool(pending), not pending)
        receipt = {'draft_id': draft_id, 'fingerprint': request_fingerprint,
                   'commits': [asdict(fact) for fact in result.commits], 'version': result.remaining_draft_version}
        serialized = json.dumps(receipt)
        if len(serialized.encode('utf-8')) > MAX_RECEIPT_BYTES:
            raise Error('INTERACTION_RESPONSE_TOO_LARGE')
        connection.execute('INSERT INTO idempotency_keys(user_id,operation,idempotency_key,response_json,created_at) VALUES (?,?,?,?,?)',
                           (user, OPERATION, idempotency_key, serialized, now))
        return result
