import json
import os
import pytest
from backend.task_evaluation.operator import Batch, prepare_packet, check_packet, run_packet
from backend.task_evaluation.live_batch import LiveConnection
from backend.tests.task_evaluation.test_live_integration import FakeProvider


def packet(tmp_path):
    directory = tmp_path/'batch'
    prepare_packet(directory, connection=LiveConnection(reference='synthetic',provider='custom',
        protocol='chat_completions', model='synthetic-model',base_url='https://example.com',
        api_key_env='FITLIFE_EVAL_API_KEY',review_mode='off'),
        batch=Batch(suite='backend/task_evaluation/scenarios/live_probe.json',
                    max_calls=12,max_tokens=250000,max_seconds=60))
    return directory


def test_prepare_and_check_create_no_authorization_and_do_not_call_provider(tmp_path, monkeypatch):
    from backend.task_evaluation import live_batch
    monkeypatch.setattr(live_batch,'production_factory',lambda *a: pytest.fail('Unexpected Provider'))
    directory = packet(tmp_path)
    check_packet(directory)
    assert not (directory/'authorization.json').exists()
    assert not (directory/'run-started.json').exists()
    assert 'unknown' in (directory/'annotations.csv').read_text(encoding='utf-8-sig')


def test_changed_connection_requires_new_batch(tmp_path):
    directory = packet(tmp_path)
    path = directory/'connection.json'
    data = json.loads(path.read_text()); data['model']='different'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='BATCH_CHANGED'):
        check_packet(directory)


def test_run_requires_explicit_confirmation_before_key_prompt(tmp_path):
    directory = packet(tmp_path)
    with pytest.raises(ValueError,match='confirm-live'):
        run_packet(directory,read_key=lambda _:pytest.fail('Unexpected key prompt'))


def test_confirmed_fake_run_retains_only_published_synthetic_messages(tmp_path):
    directory = packet(tmp_path)
    calls=[]
    assert run_packet(directory,confirm_live=True,factory=lambda:FakeProvider(calls)) == 0
    assert calls
    review=json.loads((directory/'result/review-cases.json').read_text(encoding='utf-8'))
    assert review[0]['case_id']=='live-clear-chest'
    assert {item['role'] for item in review[0]['messages']} == {'user','coach'}
    assert all(set(item)=={'role','body','truncated'} for item in review[0]['messages'])
    assert '器械' in review[0]['messages'][1]['body']
    assert review[0]['turns'][0] == {'status':'succeeded','error_code':None,'sources':[]}
    assert '器械' not in (directory/'result/report.json').read_text(encoding='utf-8')
    with pytest.raises(ValueError,match='BATCH_ALREADY_STARTED'):
        run_packet(directory,confirm_live=True,factory=lambda:FakeProvider(calls))


def test_prompted_credential_is_removed_even_if_execution_fails(tmp_path,monkeypatch):
    from backend.task_evaluation import operator
    directory=packet(tmp_path)
    monkeypatch.delenv('FITLIFE_EVAL_API_KEY',raising=False)
    def fail(*args,**kwargs):
        assert os.environ['FITLIFE_EVAL_API_KEY']=='synthetic-key'
        raise ValueError('synthetic failure')
    monkeypatch.setattr(operator,'execute',fail)
    with pytest.raises(ValueError,match='synthetic failure'):
        run_packet(directory,confirm_live=True,read_key=lambda _:'synthetic-key')
    assert 'FITLIFE_EVAL_API_KEY' not in os.environ


def test_published_citation_has_a_source_mapping_for_human_review(tmp_path):
    from backend.application.ports.structured_model_gateway import StructuredModelResult
    directory=packet(tmp_path)
    calls=[]
    class Citing(FakeProvider):
        def parse_structured(self, *, response_model, **kwargs):
            calls.append('call')
            decision = ({'kind':'call','call_id':'knowledge','tool':'knowledge.search',
                'arguments':{'query':'训练恢复','scope':'training'}} if len(calls)==1 else
                {'kind':'final','body':'根据资料 E1，应逐步训练并充分恢复。','evidence_refs':['knowledge']})
            return StructuredModelResult(response_model.model_validate({'decision':decision}),self.__class__.__name__,{'total_tokens':25})
    assert run_packet(directory,confirm_live=True,factory=lambda:Citing(calls))==0
    review=json.loads((directory/'result/review-cases.json').read_text(encoding='utf-8'))
    sources=review[0]['turns'][0]['sources']
    assert any(source['evidence_id']=='E1' and source['source'] and source['release_id'] for source in sources)


def test_acceptance_suite_is_synthetic_without_scripted_answers():
    from pathlib import Path
    from backend.task_evaluation.contracts import Suite
    suite=Suite.model_validate_json(Path('backend/task_evaluation/scenarios/live_acceptance.json').read_text(encoding='utf-8'))
    assert len(suite.scenarios)==6
    assert all(case.initial_state.faults.unified_decisions == [] for case in suite.scenarios)
