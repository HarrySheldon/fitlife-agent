"""Regression coverage for attribution after interactive catalog corrections."""
import json
from uuid import uuid4

from backend.tests.test_smart_entry_api import client, reset_settings_cache
from backend.tests.test_interactive_entry_api import BASE, _create, _post


ATTRIBUTION = ('catalog_id', 'source', 'source_name', 'source_record_id',
               'dataset_version', 'license', 'attribution', 'content_hash')


def _current_food(client, headers, draft):
    response = client.get(f"{BASE}/{draft['id']}", headers=headers)
    assert response.status_code == 200
    return response.json()['data']


def _commit(client, headers, draft, item):
    response = _post(client, headers, draft, 'confirm-items', {
        'expected_version': draft['version'],
        'selections': [{'item_id': item['item_id'], 'item_revision': item['revision']}],
    })
    assert response.status_code == 200, response.json()
    from backend.infrastructure.sqlite.runtime import get_database
    with get_database().connection() as connection:
        row = connection.execute('SELECT * FROM meal_items WHERE id=?',
            (response.json()['data']['commits'][0]['meal_item_id'],)).fetchone()
    return dict(row), response


def test_switching_catalog_replaces_attribution_in_draft_and_formal_record(client, monkeypatch):
    headers, draft = _create(client, monkeypatch,
        text='早餐：白飯 100g\n午餐：unknown-food')
    created = client.post('/api/v1/catalog/foods/custom', headers=headers, json={
        'name': 'Replacement ' + uuid4().hex[:8], 'basis_type': 'per_100g',
        'basis_amount': 100, 'unit': 'g', 'calories': 321,
        'carbs': 31, 'protein': 12, 'fat': 9,
    })
    assert created.status_code == 200
    food = created.json()['data']
    from backend.infrastructure.sqlite.runtime import get_database
    with get_database().transaction() as connection:
        connection.execute('UPDATE food_catalog SET source_name=?, source_record_id=?, '
            'dataset_version=?, license=?, attribution=?, content_hash=?, provenance_json=? WHERE id=?',
            ('Current source', 'current-record', 'current-v2', 'Current license',
             'Current attribution', 'current-hash', json.dumps({
                 'catalog_id': 'forged-id', 'source_record_id': 'forged-record',
                 'credential': 'must-not-persist'}), food['id']))
    started = _post(client, headers, draft, 'interaction/start', {'expected_version': 1}).json()['data']
    target, untouched = started['payload']['interaction']['items']
    corrected_response = _post(client, headers, draft, 'interaction/corrections', {
        'expected_version': started['version'], 'item_id': target['item_id'],
        'item_revision': target['revision'], 'updates': {'selected_catalog_id': food['id']},
    })
    assert corrected_response.status_code == 200
    corrected = corrected_response.json()['data']
    assert corrected['payload']['interaction']['items'][1] == untouched
    candidate = corrected['payload']['candidates'][0]
    expected = {'catalog_id': food['id'], 'source': 'user_custom',
        'source_name': 'Current source', 'source_record_id': 'current-record',
        'dataset_version': 'current-v2', 'license': 'Current license',
        'attribution': 'Current attribution', 'content_hash': 'current-hash'}
    assert candidate['provenance'] == expected
    recovered = _current_food(client, headers, draft)
    assert recovered == corrected
    row, response = _commit(client, headers, recovered, recovered['payload']['interaction']['items'][0])
    assert row['catalog_food_id'] == food['id']
    assert row['calories'] == 321
    assert json.loads(row['provenance_json']) == {
        **expected, 'field_sources': recovered['payload']['interaction']['items'][0]['sources']}
    # Confirmation receipts and recovery remain stable after the attribution fix.
    assert response.json()['data']['commits'][0]['record_state'] == 'unchanged'


def test_detaching_catalog_clears_old_attribution_and_retains_manual_field_sources(client, monkeypatch):
    headers, draft = _create(client, monkeypatch, text='早餐：白飯 100g')
    started = _post(client, headers, draft, 'interaction/start', {'expected_version': 1}).json()['data']
    item = started['payload']['interaction']['items'][0]
    response = _post(client, headers, draft, 'interaction/corrections', {
        'expected_version': started['version'], 'item_id': item['item_id'],
        'item_revision': item['revision'], 'updates': {
            'selected_catalog_id': None, 'name': 'Manual meal', 'calories': 250,
            'carbs': 20, 'protein': 15, 'fat': 8,
        },
    })
    assert response.status_code == 200
    corrected = response.json()['data']
    candidate = corrected['payload']['candidates'][0]
    assert candidate['selected_catalog_id'] is None
    assert not (set(ATTRIBUTION) - {'source'}) & set(candidate['provenance'])
    assert candidate['provenance'].get('source', 'user_custom') == 'user_custom'
    row, _ = _commit(client, headers, corrected, corrected['payload']['interaction']['items'][0])
    provenance = json.loads(row['provenance_json'])
    assert row['catalog_food_id'] is None
    assert row['calories'] == 250
    assert not (set(ATTRIBUTION) - {'source'}) & set(provenance)
    assert all(provenance['field_sources'][field] == 'user_provided'
               for field in ('calories', 'carbs', 'protein', 'fat'))
