"""Per-user model admission is independent of the legacy global LLM switch."""
from uuid import uuid4

import pytest

from backend.config import get_settings
from backend.domain.model_connection import ModelConnection
from backend.infrastructure.settings.file_model_connection_repository import FileModelConnectionRepository
from backend.task_evaluation.contracts import Scenario
from backend.task_evaluation.seeding import seed_environment
from backend.tests.task_evaluation.test_runner import _build_client, reset_settings_cache


@pytest.mark.parametrize('connection_state', ['enabled', 'disabled', 'absent', 'missing_key'])
def test_initial_unresolved_start_uses_only_enabled_user_connection(tmp_path, monkeypatch, connection_state):
    monkeypatch.setenv('INTERACTIVE_ENTRY_ENABLED', 'true')
    monkeypatch.setenv('LLM_ENABLED', 'false')
    client = _build_client(tmp_path, monkeypatch)
    settings = get_settings()
    actors = seed_environment(client, Scenario(id='model-admission', version=1), settings.data_dir)
    user_id = actors.user_ids['primary']
    if connection_state != 'absent':
        FileModelConnectionRepository(settings.data_dir).save(user_id, ModelConnection(
            enabled=connection_state != 'disabled',
            encrypted_api_key=None if connection_state == 'missing_key' else 'synthetic-encrypted-key'))
    calls = []
    from backend.application.ports.structured_model_gateway import StructuredModelResult
    class FakeProvider:
        model = 'synthetic-parser'
        provider = 'mock'
        def parse_structured(self, *, response_model, **kwargs):
            calls.append('parse')
            return StructuredModelResult(output=response_model(), model=self.model, usage={'input_tokens': 4, 'output_tokens': 3})
    def resolver(actor):
        assert actor == user_id
        assert connection_state == 'enabled'
        return FakeProvider()
    monkeypatch.setattr('backend.api.smart_entry.resolve_user_model_gateway', resolver)
    base = '/api/v1/smart-entry-drafts'
    created = client.post(base, headers=actors['primary'], json={
        'log_date': '2026-10-16', 'raw_text': '早餐：S2unknownFood'}).json()['data']
    started = client.post(base + '/' + created['id'] + '/interaction/start',
        headers={**actors['primary'], 'Idempotency-Key': str(uuid4())}, json={'expected_version': created['version']})
    assert started.status_code == 200, started.json()
    data = started.json()['data']
    assert data['payload']['interaction']['clarification_rounds'] == 1
    from backend.infrastructure.sqlite.runtime import get_database
    from backend.infrastructure.repositories.sqlite_task_budget_repository import SQLiteTaskBudgetRepository
    budget = SQLiteTaskBudgetRepository(get_database()).get_snapshot(user_id, created['id'])
    assert calls == (['parse'] if connection_state == 'enabled' else [])
    assert budget.spent_calls == (1 if connection_state == 'enabled' else 0)
    assert len(data['payload']['interaction']['run_ids']) == (1 if connection_state == 'enabled' else 0)

    def forbidden(*args, **kwargs):
        raise AssertionError('recovery must not access model configuration or provider')
    monkeypatch.setattr(FileModelConnectionRepository, 'get', forbidden)
    monkeypatch.setattr('backend.api.smart_entry.resolve_user_model_gateway', forbidden)
    recovered = client.get(base + '/' + created['id'], headers=actors['primary'])
    assert recovered.status_code == 200
    assert recovered.json()['data']['version'] == data['version']
