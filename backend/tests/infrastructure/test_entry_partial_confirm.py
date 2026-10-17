from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from backend.application.ports.smart_entry_repository import SmartEntryRepositoryError
from backend.domain.entry_interaction import CatalogDependency
from backend.domain.entry_resolution import catalog_signature, resolve_item
from backend.tests.application.test_smart_entry import _food

from backend.infrastructure.repositories.sqlite_smart_entry_repository import SQLiteSmartEntryRepository
from backend.tests.infrastructure.test_sqlite_smart_entry_repository import _database, _cleanup, _payload


def test_partial_confirmation_preserves_body_and_replays_after_body_deletion():
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        payload = _payload()
        values = {**payload.interaction.items[0].values, 'basis_type': 'per_100g'}
        item = replace(payload.interaction.items[0], state='ready', values=values, missing_fields=(),
                       sources={key: 'user_provided' for key in values})
        candidate = replace(payload.candidates[0], selected_catalog_id=None, values=values)
        payload = replace(payload, candidates=(candidate,),
                          interaction=replace(payload.interaction, schema_version=2, active=True, items=(item,)))
        draft = repository.create_draft('owner', payload, expires_at='2099-01-01T00:00:00Z')
        draft = repository.execute_interaction_command('owner', draft.id, expected_version=1,
            idempotency_key='activate', request_fingerprint='activate', transform=lambda current: payload)
        arguments = dict(expected_version=draft.version, selections=[{'item_id': item.item_id, 'item_revision': 1}],
                         idempotency_key='confirm', request_fingerprint='fingerprint', accepted_estimates=())
        result = repository.confirm_items('owner', draft.id, **arguments)
        assert len(result.commits) == 1
        assert repository.read_interaction_draft('owner', draft.id).payload.interaction.items[0].state == 'saved'
        repository.delete_draft('owner', draft.id)
        replay = repository.confirm_items('owner', draft.id, **arguments)
        assert replay.replayed
        assert replay.commits == result.commits
    finally:
        _cleanup(path)


def _active(repository, *, estimated=False, ratio=1):
    payload = _payload()
    values = {**payload.candidates[0].values, 'basis_type': 'per_100g', 'intake_ratio': ratio}
    first = replace(payload.candidates[0], selected_catalog_id=None, values=values)
    second = replace(first, id='second', values={**values, 'calories': None})
    draft = repository.create_draft('owner', replace(payload, candidates=(first, second)),
                                    expires_at='2099-01-01T00:00:00Z')
    items = tuple(replace(item, state='ready' if item.item_id == first.id else 'needs_clarification',
                         sources={key: 'estimated' if estimated else 'user_provided' for key in item.values},
                         missing_fields=() if item.item_id == first.id else ('calories',))
                  for item in draft.payload.interaction.items)
    return repository.execute_interaction_command('owner', draft.id, expected_version=1,
        idempotency_key='activate', request_fingerprint='activate', transform=lambda current: replace(
            current.payload, interaction=replace(current.payload.interaction, active=True, items=items)))


def _confirm(repository, draft, **overrides):
    revision = next(item.revision for item in draft.payload.interaction.items if item.item_id == 'segment-1')
    arguments = dict(expected_version=draft.version,
        selections=[{'item_id': 'segment-1', 'item_revision': revision}],
        idempotency_key='save', request_fingerprint='save')
    arguments.update(overrides)
    return repository.confirm_items('owner', draft.id, **arguments)


def test_partial_retains_missing_item_new_key_reuses_fact_and_ratio_only_scales_amount():
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = _active(repository, ratio=.5)
        result = _confirm(repository, draft)
        duplicate = _confirm(repository, draft, idempotency_key='new', request_fingerprint='new')
        assert duplicate.commits == result.commits
        current = repository.read_interaction_draft('owner', draft.id)
        assert [item.state for item in current.payload.interaction.items] == ['saved', 'needs_clarification']
        with database.connection() as connection:
            rows = connection.execute('SELECT amount,calories FROM meal_items').fetchall()
            assert len(rows) == 1
            assert tuple(rows[0]) == (25, 190)
    finally:
        _cleanup(path)


def test_all_selected_validate_before_any_write_and_foreign_is_hidden():
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = _active(repository)
        with pytest.raises(SmartEntryRepositoryError, match='ITEM_NOT_READY'):
            _confirm(repository, draft, selections=[{'item_id': item.item_id, 'item_revision': item.revision} for item in draft.payload.interaction.items])
        with pytest.raises(SmartEntryRepositoryError, match='DRAFT_NOT_FOUND'):
            repository.confirm_items('foreign', draft.id, expected_version=2, selections=[{'item_id': 'segment-1', 'item_revision': 1}], idempotency_key='x', request_fingerprint='x')
        with database.connection() as connection:
            for table in ('meals', 'meal_items', 'daily_logs', 'entry_item_commits', 'idempotency_keys'):
                assert connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
    finally:
        _cleanup(path)


def test_concurrent_confirmation_commits_once_and_record_edits_and_deletes_are_historical():
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = _active(repository)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: _confirm(repository, draft), range(2)))
        fact = results[0].commits[0]
        assert results[0].commits == results[1].commits
        with database.transaction() as connection:
            connection.execute('UPDATE meal_items SET calories=999 WHERE id=?', (fact.meal_item_id,))
        assert _confirm(repository, draft).commits[0].record_state == 'changed'
        with database.transaction() as connection:
            connection.execute('DELETE FROM meals WHERE id=?', (fact.meal_id,))
        assert _confirm(repository, draft).commits[0].record_state == 'deleted'
        with database.connection() as connection:
            assert connection.execute('SELECT COUNT(*) FROM meals').fetchone()[0] == 0
    finally:
        _cleanup(path)


def test_estimate_acceptance_is_exact_revision_and_preserves_sources():
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = _active(repository, estimated=True)
        revision = draft.payload.interaction.items[0].revision
        with pytest.raises(SmartEntryRepositoryError, match='ESTIMATE_ACCEPTANCE_REQUIRED'):
            _confirm(repository, draft)
        with pytest.raises(SmartEntryRepositoryError, match='ENTRY_COMMAND_INVALID'):
            _confirm(repository, draft, accepted_estimates=[{'item_id': 'segment-1', 'item_revision': revision + 1}])
        _confirm(repository, draft, accepted_estimates=[{'item_id': 'segment-1', 'item_revision': revision}])
        assert set(repository.read_interaction_draft('owner', draft.id).payload.interaction.items[0].sources.values()) == {'estimated'}
        with database.connection() as connection:
            assert connection.execute('SELECT is_estimate FROM meal_items').fetchone()[0] == 1
    finally:
        _cleanup(path)


def test_expiry_new_key_rejected_but_historical_receipt_survives():
    database, path = _database()
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    try:
        repository = SQLiteSmartEntryRepository(database, clock=lambda: now)
        draft = _active(repository)
        _confirm(repository, draft)
        now = datetime(2100, 1, 1, tzinfo=timezone.utc)
        assert _confirm(repository, draft).replayed
        with pytest.raises(SmartEntryRepositoryError, match='DRAFT_EXPIRED'):
            _confirm(repository, draft, idempotency_key='new', request_fingerprint='new')
    finally:
        _cleanup(path)


def test_second_insert_failure_rolls_back_records_facts_and_draft(monkeypatch):
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = _active(repository)
        second = draft.payload.interaction.items[1]
        values = {**second.values, 'calories': 100}
        payload = replace(draft.payload,
            candidates=tuple(replace(candidate, values=values) if candidate.id == 'second' else candidate for candidate in draft.payload.candidates),
            interaction=replace(draft.payload.interaction, items=(draft.payload.interaction.items[0],
                replace(second, values=values, state='ready', missing_fields=()))))
        draft = repository.execute_interaction_command('owner', draft.id, expected_version=draft.version,
            idempotency_key='ready', request_fingerprint='ready', transform=lambda current: payload)
        original = repository._insert_meals
        calls = []
        def fail_second(*args):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError('injected failure')
            return original(*args)
        monkeypatch.setattr(repository, '_insert_meals', fail_second)
        with pytest.raises(RuntimeError, match='injected failure'):
            _confirm(repository, draft, selections=[{'item_id': item.item_id, 'item_revision': item.revision} for item in draft.payload.interaction.items])
        assert repository.read_interaction_draft('owner', draft.id) == draft
        with database.connection() as connection:
            for table in ('meals', 'daily_logs', 'entry_item_commits', 'idempotency_keys'):
                assert connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
    finally:
        _cleanup(path)


def test_real_catalog_dependency_is_checked_in_confirmation_and_totals_scaled_once():
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = _active(repository, ratio=.5)
        food = _food('food-oats', '燕麦')
        with database.transaction() as connection:
            connection.execute('''INSERT INTO food_catalog (
                id,owner_user_id,source,source_name,source_record_id,dataset_version,name,
                basis_type,basis_amount,unit,calories,carbs,protein,fat,license,attribution,
                provenance_json,content_hash,active) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (food.id, None, food.source, food.source_name, food.source_record_id, food.dataset_version,
                 food.name, food.basis_type, food.basis_amount, food.unit, food.calories, food.carbs,
                 food.protein, food.fat, food.license, food.attribution, '{}', food.content_hash, 1))
        original = draft.payload.interaction.items[0]
        item = resolve_item(original, food, updates={'amount': 150})
        candidate = replace(draft.payload.candidates[0], selected_catalog_id=food.id, values=item.values)
        payload = replace(draft.payload, candidates=(candidate, draft.payload.candidates[1]),
            interaction=replace(draft.payload.interaction, items=(item, draft.payload.interaction.items[1]),
                dependencies=(CatalogDependency(item.item_id, food.id, catalog_signature(food)),)))
        draft = repository.execute_interaction_command('owner', draft.id, expected_version=draft.version,
            idempotency_key='catalog', request_fingerprint='catalog', transform=lambda current: payload)
        with database.transaction() as connection:
            connection.execute('UPDATE food_catalog SET calories=999 WHERE id=?', (food.id,))
        with pytest.raises(SmartEntryRepositoryError, match='CATALOG_DEPENDENCY_CHANGED'):
            _confirm(repository, draft)
        with database.transaction() as connection:
            assert connection.execute('SELECT COUNT(*) FROM meals').fetchone()[0] == 0
            connection.execute('UPDATE food_catalog SET calories=? WHERE id=?', (food.calories, food.id))
        _confirm(repository, draft)
        with database.connection() as connection:
            assert tuple(connection.execute('SELECT amount,calories FROM meal_items').fetchone()) == (75, 285)
    finally:
        _cleanup(path)


def test_active_legacy_confirmation_only_consumes_training_and_blocks_food_bypass():
    from backend.tests.infrastructure.test_sqlite_smart_entry_repository import _cardio_candidate
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = _active(repository)
        with pytest.raises(SmartEntryRepositoryError, match='INTERACTION_CONFIRM_ITEMS_REQUIRED'):
            repository.confirm('owner', draft.id, expected_version=draft.version,
                idempotency_key='legacy-food', request_fingerprint='legacy-food')
        payload = replace(draft.payload, candidates=(*draft.payload.candidates, _cardio_candidate('training')))
        draft = repository.execute_interaction_command('owner', draft.id, expected_version=draft.version,
            idempotency_key='add-training', request_fingerprint='add-training', transform=lambda current: payload)
        result = repository.confirm('owner', draft.id, expected_version=draft.version,
            idempotency_key='training', request_fingerprint='training')
        assert result.training_session_id is not None and result.meal_ids == ()
        current = repository.read_interaction_draft('owner', draft.id)
        assert current.payload.interaction == draft.payload.interaction
        assert all(candidate.kind == 'food' for candidate in current.payload.candidates)
        replay = repository.confirm('owner', draft.id, expected_version=draft.version,
            idempotency_key='training', request_fingerprint='training')
        assert replay.replayed
        with database.connection() as connection:
            assert connection.execute('SELECT COUNT(*) FROM meals').fetchone()[0] == 0
            assert connection.execute('SELECT COUNT(*) FROM training_sessions').fetchone()[0] == 1
    finally:
        _cleanup(path)


def test_versions_and_account_deletion_remove_only_owners_history():
    from backend.infrastructure.repositories.sqlite_profile_target_repository import SQLiteProfileTargetRepository
    from backend.infrastructure.repositories.sqlite_task_budget_repository import SQLiteTaskBudgetRepository
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = _active(repository)
        revision = draft.payload.interaction.items[0].revision
        with pytest.raises(SmartEntryRepositoryError, match='DRAFT_VERSION_CONFLICT'):
            _confirm(repository, draft, expected_version=1)
        with pytest.raises(SmartEntryRepositoryError, match='ITEM_REVISION_CONFLICT'):
            _confirm(repository, draft, selections=[{'item_id': 'segment-1', 'item_revision': revision + 1}])
        _confirm(repository, draft)
        budgets = SQLiteTaskBudgetRepository(database)
        budgets.initialize('owner', draft.id, 2, 100)
        budgets.initialize('other', 'other-task', 2, 100)
        with database.transaction() as connection:
            connection.execute('INSERT INTO entry_item_commits SELECT ?,draft_id,item_id,item_revision,meal_id,meal_item_id,record_hash,created_at FROM entry_item_commits WHERE user_id=?', ('other', 'owner'))
        SQLiteProfileTargetRepository(database).delete_user_data('owner')
        with database.connection() as connection:
            assert [row[0] for row in connection.execute('SELECT user_id FROM entry_item_commits')] == ['other']
            assert [row[0] for row in connection.execute('SELECT user_id FROM task_budgets')] == ['other']
    finally:
        _cleanup(path)


def test_active_pure_training_legacy_confirmation_preserves_original_behavior():
    from backend.application.ports.smart_entry_repository import SmartEntryDraftPayload
    from backend.tests.infrastructure.test_sqlite_smart_entry_repository import _cardio_candidate
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = repository.create_draft('owner', SmartEntryDraftPayload(
            '2026-10-15', '跑步 30分钟', 'test', (_cardio_candidate('training'),)),
            expires_at='2099-01-01T00:00:00Z')
        draft = repository.execute_interaction_command('owner', draft.id, expected_version=1,
            idempotency_key='start', request_fingerprint='start', transform=lambda current: replace(
                current.payload, interaction=replace(current.payload.interaction, active=True)))
        result = repository.confirm('owner', draft.id, expected_version=draft.version,
            idempotency_key='training', request_fingerprint='training')
        assert result.training_session_id is not None
        assert repository.get_draft('owner', draft.id) is None
    finally:
        _cleanup(path)


@pytest.mark.parametrize('corruption', ['blob', 'wrong_shape', 'oversize', 'deep'])
def test_corrupt_confirmation_receipt_returns_bounded_error(corruption):
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = _active(repository)
        _confirm(repository, draft)
        if corruption == 'blob':
            serialized = b'{"private":"body"}'
        elif corruption == 'wrong_shape':
            serialized = '{"commits":false}'
        elif corruption == 'oversize':
            serialized = '{"private":"' + 'x' * (300 * 1024) + '"}'
        else:
            serialized = '{"private":' + '[' * 950 + '0' + ']' * 950 + '}'
        with database.transaction() as connection:
            connection.execute("UPDATE idempotency_keys SET response_json=? WHERE operation='entry_confirm_items'", (serialized,))
        with pytest.raises(SmartEntryRepositoryError, match='IDEMPOTENCY_RESPONSE_CORRUPT'):
            _confirm(repository, draft)
    finally:
        _cleanup(path)


@pytest.mark.parametrize('fingerprint', [None, '', '   ', [], {}, 'x' * 201])
@pytest.mark.parametrize('receipt_exists', [False, True])
def test_confirmation_rejects_invalid_fingerprint_before_any_replay(fingerprint, receipt_exists):
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = _active(repository)
        _confirm(repository, draft)
        with pytest.raises(SmartEntryRepositoryError, match='ENTRY_COMMAND_INVALID'):
            _confirm(repository, draft, idempotency_key='save' if receipt_exists else 'new',
                     request_fingerprint=fingerprint)
    finally:
        _cleanup(path)
