from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json

import pytest

from backend.application.ports.smart_entry_repository import SmartEntryRepositoryError
from backend.infrastructure.repositories.sqlite_smart_entry_repository import SQLiteSmartEntryRepository
from backend.tests.infrastructure.test_sqlite_smart_entry_repository import _database, _cleanup, _payload


def test_command_commits_interaction_and_replays_original_snapshot_after_later_edit():
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = repository.create_draft('owner', _payload(), expires_at='2099-01-01T00:00:00Z')

        def activate(current):
            return replace(current.payload, interaction=replace(current.payload.interaction, active=True))

        first = repository.execute_interaction_command(
            'owner', draft.id, expected_version=1, idempotency_key='start',
            request_fingerprint='start-v1', transform=activate,
        )
        assert first.version == 2
        assert first.payload.interaction.active is True
        repository.execute_interaction_command(
            'owner', draft.id, expected_version=2, idempotency_key='second',
            request_fingerprint='second-v1', transform=lambda current: current.payload,
        )
        replay = repository.execute_interaction_command(
            'owner', draft.id, expected_version=1, idempotency_key='start',
            request_fingerprint='start-v1', transform=lambda current: pytest.fail('replay ran transform'),
        )
        assert replay == first
        assert repository.get_draft('owner', draft.id).version == 3
        with pytest.raises(SmartEntryRepositoryError, match='IDEMPOTENCY_KEY_REUSED'):
            repository.execute_interaction_command(
                'owner', draft.id, expected_version=1, idempotency_key='start',
                request_fingerprint='different', transform=activate,
            )
    finally:
        _cleanup(path)


def _command(repository, draft, *, key='command', version=None, transform=None, owner='owner'):
    return repository.execute_interaction_command(
        owner, draft.id, expected_version=draft.version if version is None else version,
        idempotency_key=key, request_fingerprint=key,
        transform=transform or (lambda current: current.payload),
    )


def test_command_concurrent_duplicate_applies_once_and_stale_new_command_conflicts():
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = repository.create_draft('owner', _payload(), expires_at='2099-01-01T00:00:00Z')
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: _command(repository, draft), range(2)))
        assert results[0] == results[1]
        assert results[0].version == 2
        with pytest.raises(SmartEntryRepositoryError, match='DRAFT_VERSION_CONFLICT'):
            _command(repository, draft, key='stale')
        assert repository.get_draft('owner', draft.id).version == 2
    finally:
        _cleanup(path)


def test_command_replay_checks_owner_and_expiry_before_returning_health_snapshot():
    database, path = _database()
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    try:
        repository = SQLiteSmartEntryRepository(database, clock=lambda: now)
        draft = repository.create_draft('owner', _payload(), expires_at=(now + timedelta(minutes=30)).isoformat())
        _command(repository, draft)
        with pytest.raises(SmartEntryRepositoryError, match='DRAFT_NOT_FOUND'):
            _command(repository, draft, owner='foreign')
        with pytest.raises(SmartEntryRepositoryError, match='DRAFT_NOT_FOUND'):
            repository.read_interaction_draft('foreign', draft.id)
        now += timedelta(minutes=31)
        with pytest.raises(SmartEntryRepositoryError, match='DRAFT_EXPIRED'):
            _command(repository, draft)
        with pytest.raises(SmartEntryRepositoryError, match='DRAFT_EXPIRED'):
            repository.read_interaction_draft('owner', draft.id)
    finally:
        _cleanup(path)


def test_command_snapshots_are_removed_when_draft_is_deleted():
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = repository.create_draft('owner', _payload(), expires_at='2099-01-01T00:00:00Z')
        _command(repository, draft)
        repository.delete_draft('owner', draft.id)
        with database.connection() as connection:
            assert connection.execute('SELECT COUNT(*) FROM entry_interaction_commands').fetchone()[0] == 0
            assert connection.execute('SELECT COUNT(*) FROM idempotency_keys').fetchone()[0] == 0
    finally:
        _cleanup(path)


def test_terminal_items_cannot_be_forged_by_trusted_command():
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = repository.create_draft('owner', _payload(), expires_at='2099-01-01T00:00:00Z')
        item = draft.payload.interaction.items[0]
        terminal = _command(repository, draft, transform=lambda current: replace(
            current.payload, interaction=replace(current.payload.interaction, items=(replace(item, state='saved'),))))
        with pytest.raises(SmartEntryRepositoryError, match='ITEM_NOT_EDITABLE'):
            _command(repository, terminal, key='forge', transform=lambda current: replace(
                current.payload, interaction=replace(current.payload.interaction, items=(replace(item, revision=2),))))
        assert repository.read_interaction_draft('owner', draft.id) == terminal
    finally:
        _cleanup(path)


def test_question_metadata_roundtrips_and_old_schema_two_defaults_remain_readable():
    from backend.domain.entry_interaction import EntryQuestion, EntryQuestionGroup, CatalogDependency

    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = repository.create_draft('owner', _payload(), expires_at='2099-01-01T00:00:00Z')
        group = EntryQuestionGroup('group-1', '2026-10-15T00:00:00Z', 2,
                                   (EntryQuestion('segment-1', 'amount', ('g',)),))
        result = _command(repository, draft, transform=lambda current: replace(
            current.payload, interaction=replace(current.payload.interaction, active=True,
                status='awaiting_clarification', clarification_rounds=1,
                question_groups=(group,), dependencies=(CatalogDependency('segment-1', 'food-oats', 'v1'),),
                run_ids=('run-1',))))
        assert repository.read_interaction_draft('owner', draft.id) == result
        with database.transaction() as connection:
            payload = json.loads(connection.execute('SELECT payload_json FROM record_drafts WHERE id = ?', (draft.id,)).fetchone()[0])
            for key in ('status', 'question_groups', 'dependencies', 'run_ids'):
                payload['interaction'].pop(key)
            payload['interaction']['clarification_rounds'] = 0
            connection.execute('UPDATE record_drafts SET payload_json = ? WHERE id = ?', (json.dumps(payload), draft.id))
        legacy = repository.read_interaction_draft('owner', draft.id)
        assert legacy.payload.interaction.status == 'collecting'
        assert legacy.payload.interaction.question_groups == ()
    finally:
        _cleanup(path)


@pytest.mark.parametrize('field,value', [('question_groups', {}), ('dependencies', {}), ('run_ids', 'run-1'), ('status', 'mystery')])
def test_corrupt_optional_interaction_metadata_is_rejected(field, value):
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = repository.create_draft('owner', _payload(), expires_at='2099-01-01T00:00:00Z')
        with database.transaction() as connection:
            payload = json.loads(connection.execute('SELECT payload_json FROM record_drafts WHERE id = ?', (draft.id,)).fetchone()[0])
            payload['interaction'][field] = value
            connection.execute('UPDATE record_drafts SET payload_json = ? WHERE id = ?', (json.dumps(payload), draft.id))
        with pytest.raises(SmartEntryRepositoryError, match='SMART_ENTRY_DRAFT_CORRUPT'):
            repository.read_interaction_draft('owner', draft.id)
    finally:
        _cleanup(path)


@pytest.mark.parametrize('mutation', ['unknown', 'wrong_owner', 'bad_version', 'bad_agent_status', 'bad_expiry'])
def test_corrupt_command_snapshot_is_rejected(mutation):
    database, path = _database()
    try:
        repository = SQLiteSmartEntryRepository(database)
        draft = repository.create_draft('owner', _payload(), expires_at='2099-01-01T00:00:00Z')
        _command(repository, draft)
        with database.transaction() as connection:
            response = json.loads(connection.execute('SELECT response_json FROM entry_interaction_commands').fetchone()[0])
            if mutation == 'unknown':
                response['unknown'] = 'private'
            elif mutation == 'wrong_owner':
                response['user_id'] = 'foreign'
            elif mutation == 'bad_version':
                response['version'] = True
            elif mutation == 'bad_agent_status':
                response['agent_status'] = {}
            else:
                response['expires_at'] = []
            connection.execute('UPDATE entry_interaction_commands SET response_json = ?', (json.dumps(response),))
        with pytest.raises(SmartEntryRepositoryError, match='IDEMPOTENCY_RESPONSE_CORRUPT'):
            _command(repository, draft)
    finally:
        _cleanup(path)
