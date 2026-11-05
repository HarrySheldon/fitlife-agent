"""Closed JSON-only gateway RPC. Credentials and HTTP stay in the parent."""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from uuid import uuid4
from pydantic import BaseModel, Field

from backend.application.ports.model_call_context import (
    AbortRegistry, current_abort, model_output_limit, remaining_model_timeout)
from backend.application.ports.structured_model_gateway import StructuredModelResult
from backend.task_evaluation.budget import BudgetExceeded


class WriterAnswer(BaseModel):
    answer: str = Field(max_length=20000)


class LiveModelFailure(Exception):
    def __init__(self, status_code=None):
        super().__init__('LIVE_MODEL_FAILED')
        self.status_code = status_code


def schemas():
    from backend.agent.decision import DecisionEnvelope
    from backend.safety.review import ReviewVerdict
    from backend.agent.entry_workflow import EntrySuggestions
    from backend.agent.smart_entry_analyzer import SmartEntryAnalysisResponse
    from backend.agent.grounded_answer import GroundedAnswer
    from backend.agent.planner import PlannerRoute
    from backend.schemas import GeneratedPlan
    return {cls.__name__: cls for cls in (
        DecisionEnvelope, ReviewVerdict, EntrySuggestions, SmartEntryAnalysisResponse, GroundedAnswer,
        PlannerRoute, GeneratedPlan, WriterAnswer)}


class RemoteLiveGateway:
    """Only schema IDs from this registry may cross the boundary, never Python classes."""
    def __init__(self, channel, *, model, provider):
        self.channel, self.model, self.provider = channel, model, provider
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self.attempts = self.failed_attempts = self.estimated_tokens = 0
        self.denied = False

    def parse_structured(self, *, instructions, input_text, response_model):
        abort = current_abort.get()
        if abort is not None and abort.aborted:
            from backend.agent.runtime import RunCancelled
            raise RunCancelled('Run cancelled before model request')
        if schemas().get(response_model.__name__) is not response_model:
            raise ValueError('LIVE_SCHEMA_NOT_ALLOWED')
        identity = uuid4().hex
        remaining = remaining_model_timeout.get()
        request = {'rpc': 'model', 'request_id': identity, 'schema': response_model.__name__,
                   'instructions': instructions, 'input_text': input_text,
                   'output_limit': min(model_output_limit.get() or 2048, 8192),
                   'seconds': max(0.001, remaining()) if remaining else 30.0}
        with self._lock:
            with self._send_lock:
                self.channel.send(request)
            finished = threading.Event()
            def cancel():
                if not finished.is_set():
                    try:
                        with self._send_lock:
                            self.channel.send({'rpc': 'model_cancel', 'request_id': identity})
                    except (OSError, EOFError):
                        pass
            if abort is not None:
                abort.register(cancel)
            response = self.channel.recv()
            finished.set()
        if response.get('request_id') != identity:
            raise ValueError('LIVE_RPC_MISMATCH')
        if response.get('code') == 'BUDGET_EXCEEDED':
            self.denied = True
            raise BudgetExceeded()
        self.attempts += int(response.get('attempted', False))
        if not response.get('ok'):
            self.failed_attempts += 1
            if response.get('code') == 'LIVE_MODEL_TIMEOUT':
                raise TimeoutError('LIVE_MODEL_TIMEOUT')
            raise LiveModelFailure(response.get('status_code'))
        return StructuredModelResult(response_model.model_validate(response['output']), self.model, response['usage'])

    def plan_route(self, question):
        from backend.agent.planner import PlannerRoute
        return self.parse_structured(instructions='', input_text=question, response_model=PlannerRoute).output

    def write_answer(self, state):
        from backend.agent.model_payloads import writer_payload_for_model
        payload = writer_payload_for_model(state)
        return self.parse_structured(instructions='', input_text=json.dumps(payload, ensure_ascii=False),
                                     response_model=WriterAnswer).output.answer


class LiveBroker:
    def __init__(self, factory, budget, deadline, *, model, provider):
        self.factory, self.budget, self.deadline = factory, budget, deadline
        self.model, self.provider = model, provider
        self._seen = set()
        self.attempts = self.failed = self.unknown = self.known_tokens = 0

    def handle(self, request, *, alive=lambda: True):
        identity = request.get('request_id')
        reply = {'request_id': identity, 'ok': False, 'attempted': False}
        required = {'rpc', 'request_id', 'schema', 'instructions', 'input_text', 'output_limit', 'seconds'}
        if (set(request) != required or request['rpc'] != 'model'
            or not isinstance(identity, str) or len(identity) != 32 or identity in self._seen
            or not isinstance(request['schema'], str) or request['schema'] not in schemas()
            or type(request['output_limit']) is not int or not 1 <= request['output_limit'] <= 8192
            or type(request['seconds']) not in (int, float) or not 0 < request['seconds'] <= 300
            or not all(isinstance(request[key], str) for key in ('instructions', 'input_text'))
            or len(json.dumps(request).encode()) > 262144):
            return {**reply, 'code': 'LIVE_RPC_REJECTED'}
        self._seen.add(identity)
        if time.monotonic() >= self.deadline:
            return {**reply, 'code': 'BUDGET_EXCEEDED'}
        # Conservative input byte bound + capped model output. Unknown usage retains it.
        from backend.infrastructure.model_gateway.openai_responses import PLANNER_INSTRUCTIONS, WRITER_INSTRUCTIONS
        instructions = (PLANNER_INSTRUCTIONS if request['schema'] == 'PlannerRoute' else
                        WRITER_INSTRUCTIONS if request['schema'] == 'WriterAnswer' else request['instructions'])
        schema_bytes = len(json.dumps(schemas()[request['schema']].model_json_schema()).encode())
        bound = len((instructions + request['input_text']).encode()) + schema_bytes + request['output_limit'] + 4096
        reservation = self.budget.reserve(1, bound)
        if not reservation:
            return {**reply, 'code': 'BUDGET_EXCEEDED'}
        self.attempts += 1
        abort = AbortRegistry()
        call_deadline = min(self.deadline, time.monotonic() + request['seconds'])

        def invoke():
            tokens = (current_abort.set(abort), model_output_limit.set(request['output_limit']),
                      remaining_model_timeout.set(lambda: max(.001, call_deadline - time.monotonic())))
            gateway = None
            try:
                gateway = self.factory()  # only the admitted parent owns credentials
                if request['schema'] == 'WriterAnswer':
                    from backend.agent.tasks.input_contracts import ChatInput
                    state = ChatInput.model_validate_json(request['input_text']).model_dump(mode='json')
                    return StructuredModelResult(WriterAnswer(answer=gateway.write_answer(state)), self.model, {})
                if request['schema'] == 'PlannerRoute':
                    from backend.agent.tasks.input_contracts import build_review_input
                    question = build_review_input(question=request['input_text'], draft='').question
                    return gateway.parse_structured(instructions=PLANNER_INSTRUCTIONS,
                        input_text=question, response_model=schemas()['PlannerRoute'])
                return gateway.parse_structured(instructions=request['instructions'], input_text=request['input_text'],
                                                response_model=schemas()[request['schema']])
            finally:
                if gateway is not None and callable(getattr(gateway, 'close', None)):
                    gateway.close()
                current_abort.reset(tokens[0]); model_output_limit.reset(tokens[1]); remaining_model_timeout.reset(tokens[2])

        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(invoke)
        try:
            while not future.done():
                if time.monotonic() >= call_deadline or not alive():
                    abort.abort()
                    # The cancellable production transport must finish before releasing the worker.
                    try:
                        future.result()
                    except BaseException:
                        pass
                    raise TimeoutError()
                try:
                    future.result(timeout=.02)
                except FutureTimeout:
                    pass
            result = future.result()
            output = schemas()[request['schema']].model_validate(result.output.model_dump()).model_dump(mode='json')
            if len(json.dumps(output).encode()) > 262144:
                raise ValueError('LIVE_RESPONSE_TOO_LARGE')
            usage = result.usage or {}
            total = usage.get('total_tokens')
            if type(total) is int and 0 <= total <= bound:
                self.budget.settle(reservation, 1, total)
                self.known_tokens += total
            else:
                self.budget.settle(reservation, 1, None)
                self.unknown += 1
            return {**reply, 'ok': True, 'attempted': True, 'output': output, 'usage': usage}
        except BaseException as error:
            self.failed += 1
            self.unknown += 1
            self.budget.settle(reservation, None)
            if isinstance(error, KeyboardInterrupt):
                abort.abort()
                raise
            status = getattr(error, 'status_code', None)
            # Preserve only the bounded status needed by Runtime's existing retry classifier.
            return {**reply, 'attempted': True,
                    'status_code': status if type(status) is int and 400 <= status <= 599 else None,
                    'code': 'LIVE_MODEL_TIMEOUT' if isinstance(error, TimeoutError) else 'LIVE_MODEL_FAILED'}
        finally:
            abort.abort()
            pool.shutdown(wait=True)

    def metrics(self):
        return {'gateway_attempts': self.attempts, 'failed_attempts': self.failed,
                'known_total_tokens': self.known_tokens, 'unknown_usage_count': self.unknown,
                'estimated_tokens': self.known_tokens if not self.unknown else None,
                'provider_usage': self.known_tokens if not self.unknown else None,
                'mock_usage_estimated': False, 'token_measurement': 'provider' if not self.unknown else 'unknown',
                'usage_sources': ['provider'] if not self.unknown else ['unknown'], 'model': self.model}
