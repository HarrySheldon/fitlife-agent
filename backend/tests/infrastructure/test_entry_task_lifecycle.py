from datetime import datetime, timezone
from dataclasses import replace
from unittest.mock import Mock

import json
import pytest

from backend.application.use_cases.expire_agent_tasks import ExpireAgentTasks
from backend.application.use_cases.interactive_entry import InteractiveEntryService
from backend.application.ports.smart_entry_repository import SmartEntryRepositoryError
from backend.infrastructure.repositories.sqlite_entry_task_lifecycle import SQLiteEntryTaskLifecycleRepository
from backend.infrastructure.repositories.sqlite_smart_entry_repository import SQLiteSmartEntryRepository
from backend.infrastructure.repositories.sqlite_task_budget_repository import SQLiteTaskBudgetRepository
from backend.tests.infrastructure.test_sqlite_smart_entry_repository import _database, _cleanup, _payload
from backend.tests.infrastructure.test_entry_partial_confirm import _active, _confirm
from backend.domain.entry_interaction import CatalogDependency
from backend.domain.entry_resolution import catalog_signature
from backend.tests.application.test_smart_entry import _food


def test_recreated_service_resumes_persisted_version_rounds_and_commits_without_provider():
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = _active(repository)
        confirmed = _confirm(repository, draft)
        stored = repository.read_interaction_draft('owner', draft.id)
        gateway = Mock(side_effect=AssertionError('Resume cannot call provider'))
        replacement = SQLiteSmartEntryRepository(database)
        service = InteractiveEntryService(replacement, Mock(), SQLiteTaskBudgetRepository(database),
                                           enabled=True, gateway_resolver=gateway)
        resumed = service.resume('owner', draft.id)
        assert resumed.version == stored.version
        assert resumed.payload.interaction == stored.payload.interaction
        assert replacement.list_entry_item_commits('owner', draft.id) == confirmed.commits
        gateway.assert_not_called()
    finally:
        _cleanup(path)


def test_expiry_preview_apply_offsets_owner_isolation_and_historical_confirmation():
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = _active(repository)
        confirmed = _confirm(repository, draft)
        budgets = SQLiteTaskBudgetRepository(database)
        budgets.initialize('owner', draft.id, 4, 100)
        foreign = repository.create_draft('foreign', _payload(), expires_at='2099-01-01T00:00:00Z')
        future = repository.create_draft('owner', _payload(), expires_at='2099-01-01T00:00:00Z')
        # Offset timestamp is 2020-01-01T00:00Z, not lexically later than cutoff.
        with database.transaction() as connection:
            connection.execute('UPDATE record_drafts SET expires_at=? WHERE id=?', ('2020-01-01T08:00:00+08:00', draft.id))
            connection.execute('UPDATE record_drafts SET expires_at=? WHERE id=?', ('2020-01-01T00:00:00Z', foreign.id))
        maintenance = ExpireAgentTasks(SQLiteEntryTaskLifecycleRepository(database))
        cutoff = datetime(2020, 1, 1, tzinfo=timezone.utc)
        assert maintenance.execute('owner', cutoff=cutoff).task_ids == (draft.id,)
        with pytest.raises(SmartEntryRepositoryError, match='DRAFT_EXPIRED'):
            repository.read_interaction_draft('owner', draft.id)
        assert maintenance.execute('owner', cutoff=cutoff, dry_run=False).task_ids == (draft.id,)
        with pytest.raises(SmartEntryRepositoryError, match='DRAFT_NOT_FOUND'):
            repository.read_interaction_draft('owner', draft.id)
        assert _confirm(repository, draft).commits == confirmed.commits
        assert budgets.get_snapshot('owner', draft.id).call_limit == 4
        with database.connection() as connection:
            assert connection.execute('SELECT COUNT(*) FROM meals').fetchone()[0] == 1
            assert connection.execute('SELECT COUNT(*) FROM entry_interaction_commands WHERE draft_id=?', (draft.id,)).fetchone()[0] == 0
            assert {row[0] for row in connection.execute('SELECT id FROM record_drafts')} == {foreign.id, future.id}
    finally:
        _cleanup(path)


def test_business_export_is_owner_bound_closed_and_retains_expired_bodies_and_budget_facts():
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database, clock=lambda: datetime(2019, 1, 1, tzinfo=timezone.utc))
        own = repository.create_draft('owner', _payload(raw_text='my breakfast'), expires_at='2020-01-01T00:00:00Z')
        repository.create_draft('foreign', _payload(raw_text='FOREIGN_SECRET'), expires_at='2099-01-01T00:00:00Z')
        budgets = SQLiteTaskBudgetRepository(database)
        budgets.initialize('owner', own.id, 4, 100)
        budgets.reserve('owner', own.id, 'operation', 1, 50)
        with database.transaction() as connection:
            row = connection.execute('SELECT payload_json FROM record_drafts WHERE id=?', (own.id,)).fetchone()
            body = json.loads(row[0])
            body['candidates'][0]['provenance']['api_key'] = 'PROVENANCE_SECRET'
            connection.execute('UPDATE record_drafts SET payload_json=?,agent_metadata_json=? WHERE id=?',
                (json.dumps(body), json.dumps({'raw_gateway_response': 'GATEWAY_REASONING_SECRET'}), own.id))
        adapter = SQLiteEntryTaskLifecycleRepository(database)
        data = adapter.export_entry_tasks('owner', max_bytes=5 * 1024 * 1024)
        payload = json.loads(data)
        assert payload['drafts'][0]['payload']['raw_text'] == 'my breakfast'
        assert payload['drafts'][0]['payload']['candidates'][0]['provenance'] == {'source': 'public'}
        assert payload['budgets'][0]['call_limit'] == 4
        assert payload['budgets'][0]['reserved_tokens'] == 50
        assert set(payload) == {'drafts', 'budgets', 'commits'}
        assert b'SECRET' not in data
        with pytest.raises(ValueError, match='size limit'):
            adapter.export_entry_tasks('owner', max_bytes=20)
    finally:
        _cleanup(path)


def test_expiry_delete_failure_rolls_back_every_body_and_command():
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database, clock=lambda: datetime(2019, 1, 1, tzinfo=timezone.utc))
        first = repository.create_draft('owner', _payload(), expires_at='2020-01-01T00:00:00Z')
        second = repository.create_draft('owner', _payload(), expires_at='2020-01-01T00:00:00Z')
        with database.transaction() as connection:
            connection.execute("CREATE TRIGGER reject_second_delete BEFORE DELETE ON record_drafts WHEN OLD.id = '" + sorted((first.id, second.id))[1] + "' BEGIN SELECT RAISE(ABORT, 'injected delete failure'); END")
        with pytest.raises(Exception, match='injected delete failure'):
            ExpireAgentTasks(SQLiteEntryTaskLifecycleRepository(database)).execute(
                'owner', cutoff=datetime(2020, 1, 1, tzinfo=timezone.utc), dry_run=False)
        with database.connection() as connection:
            assert connection.execute('SELECT COUNT(*) FROM record_drafts').fetchone()[0] == 2
    finally:
        _cleanup(path)


def test_expiry_compares_instants_in_both_offset_directions():
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database, clock=lambda: datetime(2019, 1, 1, tzinfo=timezone.utc))
        # Both strings start with an earlier date; only the first instant is expired.
        expired = repository.create_draft('owner', _payload(), expires_at='2019-12-31T22:00:00-01:00')
        retained = repository.create_draft('owner', _payload(), expires_at='2019-12-31T23:30:00-01:00')
        result = ExpireAgentTasks(SQLiteEntryTaskLifecycleRepository(database)).execute(
            'owner', cutoff=datetime(2020, 1, 1, tzinfo=timezone.utc), dry_run=False)
        assert result.task_ids == (expired.id,)
        with database.connection() as connection:
            assert connection.execute('SELECT id FROM record_drafts').fetchone()[0] == retained.id
    finally:
        _cleanup(path)


def test_recreated_service_catalog_change_invalidates_only_unsaved_dependent_item():
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = _active(repository)
        _confirm(repository, draft)
        current = repository.read_interaction_draft('owner', draft.id)
        food = _food('oats', '燕麦')
        signature = catalog_signature(food)
        dependencies = tuple(CatalogDependency(item.item_id, food.id, signature)
                             for item in current.payload.interaction.items)
        repository.execute_interaction_command('owner', draft.id, expected_version=current.version,
            idempotency_key='dependencies', request_fingerprint='dependencies',
            transform=lambda previous: replace(previous.payload, interaction=replace(
                previous.payload.interaction, dependencies=dependencies)))
        foods = Mock()
        foods.get_visible_food.return_value = replace(food, calories=999)
        gateway = Mock(side_effect=AssertionError('Resume cannot call provider'))
        service = InteractiveEntryService(SQLiteSmartEntryRepository(database), foods,
            SQLiteTaskBudgetRepository(database), enabled=True, gateway_resolver=gateway)
        resumed = service.resume('owner', draft.id)
        first, second = resumed.payload.interaction.items
        assert first.state == 'saved'
        assert first.values['calories'] == 190
        assert second.state == 'needs_clarification'
        assert second.values['calories'] is None
        gateway.assert_not_called()
    finally:
        _cleanup(path)


def test_export_preserves_typed_custom_food_and_workout_business_attribution():
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        payload = _payload()
        provenance = {
            'source': 'user_custom', 'catalog_id': 'my-oats', 'source_name': 'My foods',
            'source_record_id': 'record-1', 'dataset_version': 'v1',
            'license': 'Personal', 'attribution': 'My entry', 'content_hash': 'abc123',
            'api_key': 'CREDENTIAL_SENTINEL', 'gateway_response': 'GATEWAY_SENTINEL',
            'hidden_reasoning': 'REASONING_SENTINEL',
        }
        food = replace(payload.candidates[0], values={**payload.candidates[0].values,
            'source': 'user_custom'}, provenance=provenance)
        workout = replace(food, id='workout', kind='strength', raw_text='Squats',
            normalized_text='Squats', subject_text='Squats', meal_context=None,
            values={'name': 'Squats', 'source': 'user_custom', 'exercise_type': 'strength',
                'primary_muscle': 'quads', 'secondary_muscles': ['glutes', 'core'],
                'met': 6.0, 'device_calories': 120.0, 'set_count': 3, 'reps': 10,
                'load_kg': 30.0, 'bodyweight': False, 'duration_min': 15.0},
            provenance={**provenance, 'catalog_id': 'my-squats'})
        repository.create_draft('owner', replace(payload, candidates=(food, workout), interaction=None),
                                expires_at='2099-01-01T00:00:00Z')
        data = SQLiteEntryTaskLifecycleRepository(database).export_entry_tasks('owner', max_bytes=5 * 1024 * 1024)
        candidates = json.loads(data)['drafts'][0]['payload']['candidates']
        assert candidates[0]['values']['source'] == 'user_custom'
        assert candidates[0]['provenance'] == {key: value for key, value in provenance.items()
            if key not in {'api_key', 'gateway_response', 'hidden_reasoning'}}
        assert candidates[1]['values'] == workout.values
        assert candidates[1]['provenance']['catalog_id'] == 'my-squats'
        assert b'SENTINEL' not in data
    finally:
        _cleanup(path)
