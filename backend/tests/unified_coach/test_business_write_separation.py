import sqlite3
from fastapi.testclient import TestClient
from backend.config import get_settings
from backend.agent import graph
from backend.agent.decision import DecisionEnvelope
from backend.application.ports.structured_model_gateway import StructuredModelResult
from backend.main import create_app


def business_snapshot(path):
    with sqlite3.connect(path) as connection:
        existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        names = existing - {'coach_conversations', 'coach_messages', 'coach_turns'}
        return {name: connection.execute('SELECT * FROM "' + name.replace('"', '""') + '"').fetchall()
                for name in sorted(names)}


def test_advice_changes_only_coach_records_not_business_state(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('SQLITE_DATABASE_PATH', str(tmp_path / 'fitlife.sqlite3'))
    monkeypatch.setenv('COACH_AGENT_MODE', 'unified')
    get_settings.cache_clear()
    decisions = iter([
        {'kind': 'call', 'call_id': 'plan', 'tool': 'fitness.calculate', 'arguments': {
            'operation': 'validate_training', 'exercises': [{'name': '俯卧撑', 'sets': 3, 'reps': 10, 'rest_seconds': 60}]}},
        {'kind': 'final', 'body': '以下仅为训练建议，不适时停止。', 'evidence_refs': ['plan']},
    ])
    class Gateway:
        model = 'synthetic'
        def parse_structured(self, **kwargs):
            return StructuredModelResult(DecisionEnvelope.model_validate({'decision': next(decisions)}), self.model, {})
    monkeypatch.setattr(graph, '_resolve_gateway', lambda *a: Gateway())
    try:
        with TestClient(create_app()) as client:
            registration = client.post('/auth/register', json={'username': 'isolated', 'password': 'synthetic123456',
                                                               'display_name': 'Synthetic'}).json()['data']
            headers = {'Authorization': 'Bearer ' + registration['access_token']}
            root = tmp_path / 'users' / registration['user']['user_id']
            (root / 'plans').mkdir(parents=True, exist_ok=True)
            (root / 'plan-drafts').mkdir(parents=True, exist_ok=True)
            sentinel = root / 'plans' / 'existing.json'
            sentinel.write_text('{"synthetic_existing_plan":"unchanged"}', encoding='utf-8')
            (root / 'plan-drafts' / 'existing.json').write_text('{"synthetic_draft":"unchanged"}', encoding='utf-8')
            def plans_snapshot():
                return {str(path.relative_to(root)): path.read_bytes() for folder in ('plans', 'plan-drafts')
                        for path in (root / folder).rglob('*') if path.is_file()}
            before_files = plans_snapshot()
            before = business_snapshot(tmp_path / 'fitlife.sqlite3')
            response = client.post('/chat', headers=headers, json={'question': '今天练胸，请给训练建议'})
            assert response.status_code == 200, response.text
            assert '3' in response.json()['data']['answer_markdown']
            assert business_snapshot(tmp_path / 'fitlife.sqlite3') == before
            assert plans_snapshot() == before_files
    finally:
        get_settings.cache_clear()
