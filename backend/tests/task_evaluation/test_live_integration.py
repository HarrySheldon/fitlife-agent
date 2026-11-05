import json
import os
import time
from pathlib import Path
from uuid import uuid4
import pytest
from backend.task_evaluation.cli import main, parse_args
from backend.task_evaluation.live_batch import prepare
from backend.task_evaluation.live_rpc import LiveBroker
from backend.task_evaluation.budget import BatchBudget
from backend.task_evaluation.provenance import fingerprint
from backend.application.ports.structured_model_gateway import StructuredModelResult


class FakeProvider:
    def __init__(self, calls):
        self.calls = calls

    def parse_structured(self, *, response_model, **kwargs):
        self.calls.append((os.getpid(), response_model.__name__))
        if response_model.__name__ == 'DecisionEnvelope':
            output = {'decision': {'kind': 'ask', 'question': '你可用的器械有哪些？'}}
        elif response_model.__name__ == 'ReviewVerdict':
            output = {'outcome': 'allow', 'risk_category': 'low'}
        else:
            raise ValueError('UNEXPECTED_SCHEMA')
        return StructuredModelResult(response_model.model_validate(output), 'synthetic-model', {'total_tokens': 25})

    def close(self):
        pass


@pytest.fixture
def inputs(tmp_path):
    root = Path(__file__).resolve().parents[2] / 'task_evaluation/scenarios'
    path = root / f'live-test-{uuid4().hex}.json'
    original = json.loads((root / 'unified_coach.json').read_text(encoding='utf-8'))
    scenario = original['scenarios'][0]
    scenario.pop('initial_state', None)
    scenario['expected'] = {'terminal': 'succeeded'}
    path.write_text(json.dumps({'schema_version': 1, 'scenarios': [scenario]}), encoding='utf-8')
    connection = tmp_path / 'connection.json'
    connection.write_text(json.dumps({'reference': 'synthetic', 'provider': 'custom',
        'protocol': 'chat_completions', 'model': 'synthetic-model', 'base_url': 'https://example.com',
        'api_key_env': 'FITLIFE_EVAL_API_KEY', 'review_mode': 'off'}), encoding='utf-8')
    flags = ['--mode','live','--allow-live','--suite',str(path), '--connection', str(connection),
        '--max-calls','4','--max-tokens','120000','--max-seconds','60','--output',str(tmp_path/'out')]
    try:
        yield flags, tmp_path
    finally:
        path.unlink(missing_ok=True)


def approve(flags, directory):
    args = parse_args(flags)
    _, _, manifest, _ = prepare(args)
    manifest_path, auth_path = directory/'manifest.json', directory/'auth.json'
    manifest_path.write_text(manifest.model_dump_json(), encoding='utf-8')
    auth_path.write_text(json.dumps({'approved_by': 'offline-test', 'expires_at': time.time()+120,
        'reference': 'synthetic-test-only', 'manifest_digest': fingerprint(manifest.model_dump(mode='json'))}), encoding='utf-8')
    return [*flags, '--manifest',str(manifest_path),'--authorization',str(auth_path)]


def test_cli_live_reaches_isolated_business_api_and_parent_provider(inputs, monkeypatch):
    flags, directory = inputs
    flags = approve(flags, directory)
    calls = []
    from backend.task_evaluation import live_batch
    monkeypatch.setattr(live_batch, 'production_factory', lambda connection: FakeProvider(calls))
    assert main(flags) == 0
    assert calls and all(pid == os.getpid() for pid, _ in calls)
    report = json.loads((directory/'out/report.json').read_text())
    assert report['records'][0]['mode'] == 'live'
    assert report['records'][0]['total_tokens'] == 25
    assert report['records'][0]['calls'] == 1
    assert not (directory/'out/review-cases.json').exists()


def test_dry_run_and_refused_manifest_never_build_provider(inputs, monkeypatch):
    flags, directory = inputs
    flags = approve(flags, directory)
    from backend.task_evaluation import live_batch
    def forbidden(*args):
        pytest.fail('Provider constructed before authorization')
    monkeypatch.setattr(live_batch, 'production_factory', forbidden)
    assert main([*flags, '--dry-run']) == 0
    path = directory/'manifest.json'
    value = json.loads(path.read_text()); value['model'] = 'changed'
    path.write_text(json.dumps(value))
    assert main(flags) == 2


def test_compare_arms_share_one_budget_and_preserve_failed_arm(inputs, monkeypatch):
    flags, directory = inputs
    flags = approve([*flags, '--phase', 'compare', '--max-calls', '1'], directory)
    calls = []
    from backend.task_evaluation import live_batch
    monkeypatch.setattr(live_batch, 'production_factory', lambda connection: FakeProvider(calls))
    assert main(flags) == 1
    assert len(calls) == 1
    left = json.loads((directory/'out/reference/report.json').read_text())
    right = json.loads((directory/'out/optimized/report.json').read_text())
    assert len(left['records']) == len(right['records']) == 1
    assert left['records'][0]['success']
    assert not right['records'][0]['success']


def test_enforced_review_is_a_second_metered_call(inputs, monkeypatch):
    flags, directory = inputs
    connection_path = Path(flags[flags.index('--connection')+1])
    value = json.loads(connection_path.read_text()); value['review_mode'] = 'enforce'
    connection_path.write_text(json.dumps(value))
    flags = approve(flags, directory)
    calls = []
    from backend.task_evaluation import live_batch
    monkeypatch.setattr(live_batch, 'production_factory', lambda connection: FakeProvider(calls))
    assert main(flags) == 0
    assert [schema for _, schema in calls] == ['DecisionEnvelope', 'ReviewVerdict']
    record = json.loads((directory/'out/report.json').read_text())['records'][0]
    assert record['total_tokens'] == 50
    assert record['calls'] == 2


def test_interruption_retains_current_case_and_unknown_cost(inputs, monkeypatch):
    flags, directory = inputs
    flags = approve(flags, directory)
    class Interrupted(FakeProvider):
        def parse_structured(self, **kwargs):
            raise KeyboardInterrupt()
    from backend.task_evaluation import live_batch
    monkeypatch.setattr(live_batch, 'production_factory', lambda connection: Interrupted([]))
    assert main(flags) == 130
    record = json.loads((directory/'out/report.json').read_text())['records'][0]
    assert record['error_class'] == 'interrupted'
    assert record['calls'] == 1 and record['total_tokens'] is None
    manifest = json.loads((directory/'out/manifest.json').read_text())
    assert manifest['partial']
    assert manifest['ledger']['reserved_calls'] == 1


def test_transient_retry_is_metered_and_unknown_usage_preserves_known_subtotal(inputs, monkeypatch):
    flags, directory = inputs
    flags = approve(flags, directory)
    calls = []
    class TransientError(Exception):
        status_code = 500
    class Retry(FakeProvider):
        def parse_structured(self, **kwargs):
            if not calls:
                calls.append(('failed', 'attempt'))
                raise TransientError()
            return super().parse_structured(**kwargs)
    from backend.task_evaluation import live_batch
    monkeypatch.setattr(live_batch, 'production_factory', lambda connection: Retry(calls))
    assert main(flags) == 0
    report = json.loads((directory/'out/report.json').read_text())
    record = report['records'][0]
    assert record['calls'] == 2 and record['total_tokens'] is None
    assert record['details']['known_total_tokens'] == 25
    assert report['groups']['live']['known_total_tokens'] == 25


def request():
    return {'rpc':'model','request_id':'a'*32,'schema':'DecisionEnvelope',
            'instructions':'Return a decision', 'input_text':'synthetic', 'output_limit':100,'seconds':1.0}


def test_broker_rejects_unknown_schema_replay_and_budget_before_provider():
    calls = []
    broker = LiveBroker(lambda: FakeProvider(calls), BatchBudget(1,10000), time.monotonic()+10,
                        model='synthetic', provider='fake')
    assert broker.handle({**request(),'schema':'os.system'})['code'] == 'LIVE_RPC_REJECTED'
    assert broker.handle(request())['ok']
    assert broker.handle(request())['code'] == 'LIVE_RPC_REJECTED'
    assert broker.handle({**request(),'request_id':'b'*32})['code'] == 'BUDGET_EXCEEDED'
    assert len(calls) == 1


def test_broker_timeout_closes_transport_and_retains_unknown_reservation():
    from backend.application.ports.model_call_context import current_abort
    import threading
    exited = threading.Event()
    class Slow:
        def parse_structured(self, **kwargs):
            stopped = threading.Event()
            current_abort.get().register(stopped.set)
            stopped.wait(5)
            exited.set()
            raise TimeoutError()
    budget = BatchBudget(1,10000)
    broker = LiveBroker(Slow, budget, time.monotonic()+1, model='synthetic',provider='fake')
    assert broker.handle({**request(),'seconds':.03})['code'] == 'LIVE_MODEL_TIMEOUT'
    assert exited.is_set()
    assert budget.snapshot()['reserved_calls'] == 1
    assert broker.metrics()['unknown_usage_count'] == 1


def test_unknown_usage_is_not_zero_and_prevents_reusing_reserved_tokens():
    class Unknown(FakeProvider):
        def parse_structured(self, **kwargs):
            result = super().parse_structured(**kwargs)
            return StructuredModelResult(result.output, result.model, {})
    calls = []
    from backend.task_evaluation.live_rpc import schemas
    bound = len((request()['instructions'] + request()['input_text']).encode()) + len(json.dumps(
        schemas()['DecisionEnvelope'].model_json_schema()).encode()) + 100 + 4096
    budget = BatchBudget(4,bound)
    broker = LiveBroker(lambda: Unknown(calls), budget, time.monotonic()+10,
                        model='synthetic',provider='fake')
    assert broker.handle(request())['ok']
    assert broker.metrics()['estimated_tokens'] is None
    assert budget.snapshot()['reserved_tokens'] > 0
    assert broker.handle({**request(),'request_id':'b'*32})['code'] == 'BUDGET_EXCEEDED'


def test_worker_exit_aborts_active_request_before_broker_returns():
    from backend.application.ports.model_call_context import current_abort
    import threading
    exited = threading.Event()
    class Cancelable:
        def parse_structured(self, **kwargs):
            stop = threading.Event()
            current_abort.get().register(stop.set)
            stop.wait(5)
            exited.set()
            raise TimeoutError()
    broker = LiveBroker(Cancelable, BatchBudget(2,10000), time.monotonic()+5,
                        model='synthetic',provider='fake')
    assert not broker.handle(request(), alive=lambda: False)['ok']
    assert exited.is_set()


def test_native_writer_and_planner_use_closed_rpc_operations():
    from backend.agent.planner import PlannerRoute
    class Native:
        def write_answer(self, state):
            return '请充分恢复。'
        def parse_structured(self, *, instructions, input_text, response_model):
            from backend.application.ports.model_call_context import model_output_limit
            from backend.infrastructure.model_gateway.openai_responses import PLANNER_INSTRUCTIONS
            assert model_output_limit.get() == 100
            assert instructions == PLANNER_INSTRUCTIONS
            return StructuredModelResult(PlannerRoute(intent='general'), 'synthetic', {'total_tokens':5})
    broker = LiveBroker(Native, BatchBudget(2,20000), time.monotonic()+10,
                        model='synthetic', provider='fake')
    state = {'user_query':'恢复', 'intent':'general', 'context_metadata':{}, 'profile':{},
             'tool_results':{}, 'retrieved_docs':[], 'validation_result':{}}
    assert broker.handle({**request(), 'schema':'WriterAnswer', 'input_text':json.dumps(state)})['output']['answer']
    assert broker.handle({**request(), 'request_id':'b'*32, 'schema':'PlannerRoute'})['output']['intent'] == 'general'
    assert broker.metrics()['estimated_tokens'] is None  # native methods do not expose usage


def test_remote_abort_reaches_parent_transport():
    import multiprocessing
    import threading
    from backend.task_evaluation.live_rpc import RemoteLiveGateway, schemas
    from backend.application.ports.model_call_context import AbortRegistry, current_abort
    parent, child = multiprocessing.Pipe()
    started, exited = threading.Event(), threading.Event()
    class Cancelable:
        def parse_structured(self, **kwargs):
            stop = threading.Event()
            current_abort.get().register(stop.set)
            started.set()
            stop.wait(5)
            exited.set()
            raise TimeoutError()
    broker = LiveBroker(Cancelable, BatchBudget(1,10000), time.monotonic()+5,
                        model='synthetic', provider='fake')
    abort = AbortRegistry()
    errors = []
    def client():
        token = current_abort.set(abort)
        try:
            RemoteLiveGateway(child, model='synthetic',provider='fake').parse_structured(
                instructions='synthetic', input_text='synthetic', response_model=schemas()['DecisionEnvelope'])
        except Exception as error:
            errors.append(error)
        finally:
            current_abort.reset(token)
    def server():
        message = parent.recv()
        def alive():
            if parent.poll():
                cancel = parent.recv()
                return cancel != {'rpc':'model_cancel','request_id':message['request_id']}
            return True
        parent.send(broker.handle(message, alive=alive))
    workers = [threading.Thread(target=client), threading.Thread(target=server)]
    for worker in workers:
        worker.start()
    assert started.wait(2)
    abort.abort()
    for worker in workers:
        worker.join(3)
        assert not worker.is_alive()
    parent.close(); child.close()
    assert exited.is_set() and errors
