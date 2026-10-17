"""The active food protocol must leave the legacy training editor usable."""
from copy import deepcopy
from uuid import uuid4

import pytest

from backend.tests.test_smart_entry_api import client, reset_settings_cache, _profile, _register
from backend.tests.test_interactive_entry_api import BASE, _create, _post


def _mutation(draft):
    return {key: deepcopy(value) for key, value in draft['payload'].items() if key != 'interaction'}


def _start(client, monkeypatch):
    monkeypatch.setenv('INTERACTIVE_ENTRY_ENABLED', 'true')
    from backend.config import get_settings
    get_settings.cache_clear()
    headers = _register(client, 'mixed-training-' + uuid4().hex[:10])
    cardio_name = 'Review cardio ' + uuid4().hex[:10]
    catalog_response = client.post('/api/v1/catalog/exercises/custom', headers=headers, json={
        'name': cardio_name, 'exercise_type': 'cardio', 'primary_muscle': 'cardio',
        'secondary_muscles': [], 'met': 6, 'aliases': [],
    })
    assert catalog_response.status_code == 200, catalog_response.json()
    draft_response = client.post(BASE, headers=headers, json={
        'log_date': '2026-07-26',
        'raw_text': f'早餐：白飯 100g\n午餐：unknown-food\n力量：杠铃深蹲\n有氧：{cardio_name}',
    })
    assert draft_response.status_code == 200, draft_response.json()
    draft = draft_response.json()['data']
    cardio = next(item for item in draft['payload']['candidates'] if item['kind'] == 'cardio')
    assert cardio['selected_catalog_id'] == catalog_response.json()['data']['id']
    assert 'SMART_ENTRY_CARDIO_DURATION_REQUIRED' in cardio['issues']
    _profile(client, headers)
    response = _post(client, headers, draft, 'interaction/start', {'expected_version': 1})
    assert response.status_code == 200
    return headers, response.json()['data']


def _complete_training(draft):
    payload = _mutation(draft)
    for candidate in payload['candidates']:
        if candidate['kind'] == 'strength':
            candidate['values'].update(set_count=3, reps=8, load_kg=60)
        elif candidate['kind'] == 'cardio':
            candidate['values'].update(duration_min=30, device_calories=200)
    return payload


@pytest.mark.parametrize('enabled', [True, False])
def test_active_mixed_training_can_be_completed_and_confirmed_without_touching_food(client, monkeypatch, enabled):
    headers, active = _start(client, monkeypatch)
    ready = next(item for item in active['payload']['interaction']['items'] if item['state'] == 'ready')
    saved = _post(client, headers, active, 'confirm-items', {
        'expected_version': active['version'],
        'selections': [{'item_id': ready['item_id'], 'item_revision': ready['revision']}],
    })
    assert saved.status_code == 200
    active = client.get(f"{BASE}/{active['id']}", headers=headers).json()['data']
    original_food = [item for item in active['payload']['candidates'] if item['kind'] == 'food']
    monkeypatch.setenv('INTERACTIVE_ENTRY_ENABLED', str(enabled).lower())
    from backend.config import get_settings
    get_settings.cache_clear()
    response = client.patch(f"{BASE}/{active['id']}",
        headers={**headers, 'If-Match': str(active['version'])}, json=_complete_training(active))
    assert response.status_code == 200, response.json()
    edited = response.json()['data']
    assert edited['version'] == active['version'] + 1
    assert edited['payload']['interaction'] == active['payload']['interaction']
    assert edited['item_commits'] == active['item_commits']
    assert [item for item in edited['payload']['candidates'] if item['kind'] == 'food'] == original_food
    training = [item for item in edited['payload']['candidates'] if item['kind'] != 'food']
    assert all(not item['issues'] for item in training), [
        (item['kind'], item['subject_text'], item['selected_catalog_id'],
         [(choice['id'], choice['name']) for choice in item['catalog_choices']],
         item['issues'], sorted(item['values'])) for item in training
    ]
    key = str(uuid4())
    confirmed = client.post(f"{BASE}/{active['id']}/confirm",
        headers={**headers, 'If-Match': str(edited['version']), 'Idempotency-Key': key})
    assert confirmed.status_code == 200, confirmed.json()
    assert confirmed.json()['data']['training_session_id']
    assert confirmed.json()['data']['meal_ids'] == []
    replay = client.post(f"{BASE}/{active['id']}/confirm",
        headers={**headers, 'If-Match': str(edited['version']), 'Idempotency-Key': key})
    assert replay.status_code == 200
    assert replay.json()['data']['replayed'] is True
    remaining = client.get(f"{BASE}/{active['id']}", headers=headers).json()['data']
    assert remaining['payload']['candidates'] == original_food
    assert remaining['payload']['interaction'] == active['payload']['interaction']
    assert remaining['item_commits'] == active['item_commits']


@pytest.mark.parametrize('tamper', ['food_value', 'food_provenance', 'food_selected',
    'food_catalog', 'log_date', 'raw_text', 'parser_version', 'kind', 'id', 'remove', 'interaction'])
def test_active_training_update_rejects_food_identity_and_interaction_mutations(client, monkeypatch, tamper):
    headers, active = _start(client, monkeypatch)
    payload = _complete_training(active)
    food = next(item for item in payload['candidates'] if item['kind'] == 'food')
    training = next(item for item in payload['candidates'] if item['kind'] == 'strength')
    if tamper == 'food_value':
        # Catalog normalization must not conceal the malicious submitted value.
        food['values']['calories'] = 999999
    elif tamper == 'food_provenance':
        food['provenance']['source_record_id'] = 'forged'
    elif tamper == 'food_selected':
        food['selected'] = False
    elif tamper == 'food_catalog':
        food['selected_catalog_id'] = None
    elif tamper in ('log_date', 'raw_text', 'parser_version'):
        payload[tamper] = {'log_date': '2026-07-27', 'raw_text': 'different source',
                           'parser_version': 'forged'}[tamper]
    elif tamper == 'kind':
        training['kind'] = 'food'
    elif tamper == 'id':
        training['id'] = 'forged'
    elif tamper == 'remove':
        payload['candidates'].remove(food)
    else:
        payload['interaction'] = deepcopy(active['payload']['interaction'])
        payload['interaction']['clarification_rounds'] = 0
    response = client.patch(f"{BASE}/{active['id']}",
        headers={**headers, 'If-Match': str(active['version'])}, json=payload)
    assert response.status_code == 422, response.json()
    assert client.get(f"{BASE}/{active['id']}", headers=headers).json()['data'] == active


@pytest.mark.parametrize('boundary,status', [('foreign', 404), ('stale', 409), ('expired', 410)])
def test_active_training_update_retains_owner_cas_and_expiry(client, monkeypatch, boundary, status):
    headers, active = _start(client, monkeypatch)
    version = active['version']
    if boundary == 'foreign':
        headers = _register(client, 'training-foreign-' + uuid4().hex[:8])
    elif boundary == 'stale':
        version -= 1
    else:
        from backend.infrastructure.sqlite.runtime import get_database
        with get_database().transaction() as connection:
            connection.execute("UPDATE record_drafts SET expires_at='2000-01-01T00:00:00Z' WHERE id=?", (active['id'],))
    response = client.patch(f"{BASE}/{active['id']}",
        headers={**headers, 'If-Match': str(version)}, json=_complete_training(active))
    assert response.status_code == status, response.json()


def test_active_training_can_choose_an_ambiguous_catalog_match(client, monkeypatch):
    headers, _ = _create(client, monkeypatch, text='早餐：白飯 100g')
    alias = 'review-lift-' + uuid4().hex[:8]
    choices = []
    for suffix in ('A', 'B'):
        response = client.post('/api/v1/catalog/exercises/custom', headers=headers, json={
            'name': 'Review lift ' + suffix, 'exercise_type': 'strength',
            'primary_muscle': 'quadriceps', 'secondary_muscles': ['glutes'],
            'met': None, 'aliases': [alias],
        })
        assert response.status_code == 200
        choices.append(response.json()['data'])
    draft = client.post(BASE, headers=headers, json={
        'log_date': '2026-07-26', 'raw_text': f'早餐：白飯 100g\n力量：{alias} 3x8 60kg',
    }).json()['data']
    active = _post(client, headers, draft, 'interaction/start', {'expected_version': 1}).json()['data']
    payload = _mutation(active)
    training = next(item for item in payload['candidates'] if item['kind'] == 'strength')
    assert len(training['catalog_choices']) == 2
    assert training['selected_catalog_id'] is None
    training['selected_catalog_id'] = choices[1]['id']
    training['issues'] = []
    response = client.patch(f"{BASE}/{active['id']}",
        headers={**headers, 'If-Match': str(active['version'])}, json=payload)
    assert response.status_code == 200, response.json()
    edited = response.json()['data']
    resolved = next(item for item in edited['payload']['candidates'] if item['kind'] == 'strength')
    assert resolved['values']['name'] == choices[1]['name']
    assert resolved['catalog_choices'] == training['catalog_choices']
    assert resolved['selected_catalog_id'] == choices[1]['id']
    assert not resolved['issues']
    assert edited['payload']['interaction'] == active['payload']['interaction']
