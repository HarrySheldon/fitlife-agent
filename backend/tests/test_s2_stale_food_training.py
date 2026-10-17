"""A read-only stale food projection must not block unrelated training edits."""
from uuid import uuid4

import pytest

from backend.config import get_settings
from backend.infrastructure.repositories.sqlite_smart_entry_repository import SQLiteSmartEntryRepository
from backend.infrastructure.sqlite.runtime import get_database
from backend.tests.test_interactive_entry_api import BASE
from backend.tests.test_s2_mixed_training_regression import _complete_training, _start
from backend.tests.test_smart_entry_api import client, reset_settings_cache


def _stale_food(client, monkeypatch, enabled, catalog_change):
    headers, active = _start(client, monkeypatch)
    database = get_database()
    repository = SQLiteSmartEntryRepository(database)
    stored = repository.read_interaction_draft(active['user_id'], active['id'])
    food = next(item for item in stored.payload.candidates
                if item.kind == 'food' and item.selected_catalog_id is not None)
    with database.transaction() as connection:
        if catalog_change == 'change':
            connection.execute('UPDATE food_catalog SET calories=calories+1 WHERE id=?',
                               (food.selected_catalog_id,))
        else:
            connection.execute('UPDATE food_catalog SET active=0 WHERE id=?',
                               (food.selected_catalog_id,))
    monkeypatch.setenv('INTERACTIVE_ENTRY_ENABLED', str(enabled).lower())
    get_settings.cache_clear()
    response = client.get(f"{BASE}/{active['id']}", headers=headers)
    assert response.status_code == 200, response.json()
    resumed = response.json()['data']
    projected_food = next(item for item in resumed['payload']['candidates'] if item['id'] == food.id)
    projected_item = next(item for item in resumed['payload']['interaction']['items']
                          if item['item_id'] == food.id)
    assert projected_food['values']['calories'] is None
    assert projected_item['sources']['calories'] == 'unknown'
    assert repository.read_interaction_draft(stored.user_id, stored.id) == stored
    return headers, resumed, stored, repository


def _assert_food_untouched(stored, current):
    assert tuple(item for item in current.payload.candidates if item.kind == 'food') == tuple(
        item for item in stored.payload.candidates if item.kind == 'food')
    # Includes items, dependencies, rounds, questions, and all interaction metadata.
    assert current.payload.interaction == stored.payload.interaction
    with get_database().connection() as connection:
        assert connection.execute('SELECT COUNT(*) FROM meals WHERE user_id=?',
                                  (stored.user_id,)).fetchone()[0] == 0


@pytest.mark.parametrize('enabled', [True, False])
@pytest.mark.parametrize('catalog_change', ['change', 'deactivate'])
def test_stale_food_projection_allows_training_patch_and_confirmation(client, monkeypatch, enabled, catalog_change):
    headers, resumed, stored, repository = _stale_food(client, monkeypatch, enabled, catalog_change)
    response = client.patch(f"{BASE}/{stored.id}",
        headers={**headers, 'If-Match': str(resumed['version'])}, json=_complete_training(resumed))
    assert response.status_code == 200, response.json()
    edited = response.json()['data']
    assert edited['version'] == stored.version + 1
    projected_food = next(item for item in edited['payload']['candidates']
                          if item['kind'] == 'food' and item['selected_catalog_id'] is not None)
    assert projected_food['values']['calories'] is None
    projected_item = next(item for item in edited['payload']['interaction']['items']
                          if item['item_id'] == projected_food['id'])
    assert projected_item['sources']['calories'] == 'unknown'
    assert any(dependency['item_id'] == projected_food['id'] and not dependency['valid']
               for dependency in edited['dependency_validity'])
    assert all(not item['issues'] for item in edited['payload']['candidates'] if item['kind'] != 'food')
    _assert_food_untouched(stored, repository.read_interaction_draft(stored.user_id, stored.id))
    confirmed = client.post(f"{BASE}/{stored.id}/confirm", headers={**headers,
        'If-Match': str(edited['version']), 'Idempotency-Key': str(uuid4())})
    assert confirmed.status_code == 200, confirmed.json()
    assert confirmed.json()['data']['training_session_id']
    assert confirmed.json()['data']['meal_ids'] == []
    remaining = repository.read_interaction_draft(stored.user_id, stored.id)
    assert all(item.kind == 'food' for item in remaining.payload.candidates)
    _assert_food_untouched(stored, remaining)


@pytest.mark.parametrize('enabled', [True, False])
@pytest.mark.parametrize('catalog_change', ['change', 'deactivate'])
def test_stale_food_projection_does_not_authorize_food_value_changes(client, monkeypatch, enabled, catalog_change):
    headers, resumed, stored, repository = _stale_food(client, monkeypatch, enabled, catalog_change)
    payload = _complete_training(resumed)
    food = next(item for item in payload['candidates']
                if item['kind'] == 'food' and item['selected_catalog_id'] is not None)
    food['values']['calories'] = 999999
    response = client.patch(f"{BASE}/{stored.id}",
        headers={**headers, 'If-Match': str(resumed['version'])}, json=payload)
    assert response.status_code == 422, response.json()
    assert repository.read_interaction_draft(stored.user_id, stored.id) == stored
    _assert_food_untouched(stored, stored)
