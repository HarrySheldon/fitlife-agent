from __future__ import annotations

import asyncio
import inspect
import json
import random as random_module
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from contextvars import copy_context
from threading import BoundedSemaphore, Event, RLock, Thread
from typing import Literal, TypeVar
from uuid import uuid4
from backend.agent.contracts import AgentCommand, AgentOutcome, AgentRunSnapshot, AgentWorkflow, CancelResult
from backend.agent.failures import Disposition, classify_failure, decide_disposition
from backend.agent.policy import RuntimePolicy
from backend.agent.persistence import ERROR_CODES, TERMINAL_STATUSES, utc_now
from backend.agent.telemetry import SafeTelemetryContext
from backend.infrastructure.agent_runtime.memory_run_repository import MemoryCheckpointStore, MemoryRunRepository
from backend.application.ports.model_call_context import remaining_model_timeout
from backend.configuration.resolver import ConfigurationResolver
from backend.configuration.models import EffectiveRunConfig, RunPolicySnapshot
from backend.infrastructure.agent_runtime.rate_limiter import ProcessRateLimiter
from backend.agent.safety import check_input, review_output, SafetyRefusal, SAFETY_RULE_VERSION
from backend.domain.errors import ApplicationError
T = TypeVar("T")
_SYNC_SLOTS = BoundedSemaphore(16)


def _consume_completion(task):
    if not task.cancelled():
        task.exception()

class RuntimeControlError(Exception):
    code = "RUNTIME_ERROR"
    def __init__(self, message: str, *, run_id: str = "", request_id: str = ""):
        super().__init__(message)
        self.run_id = run_id
        self.request_id = request_id


class RunCancelled(RuntimeControlError):
    code = "RUN_CANCELLED"


class RunTimedOut(RuntimeControlError):
    code = "RUN_TIMED_OUT"


class BudgetExceeded(RuntimeControlError):
    code = "RUN_BUDGET_EXCEEDED"


async def _sleep(delay: float):
    await asyncio.sleep(delay)

class RuntimeContext:
    def __init__(self, *, policy=None, clock=time.monotonic, sleeper=_sleep, random_value=random_module.random,
                 token_estimator=None, cancel_event=None, deadline_at=None, record=None, telemetry=None,
                 checkpoint_store=None, run_id=None, user_id=None):
        self.policy = policy or RuntimePolicy()
        self.clock = clock
        self.sleeper = sleeper
        self.random_value = random_value
        self.token_estimator = token_estimator or (lambda text: max(1, (len(text) + 3) // 4))
        self.cancel_event = cancel_event or Event()
        self.deadline_at = deadline_at if deadline_at is not None else clock() + self.policy.deadline_seconds
        self.completed_steps = []
        self.completed_tools = []
        self.current_step = None
        self.attempt = 0
        self.input_chars = self.tokens = self.model_calls = self.tool_calls = 0
        self.record = record or (lambda *args, **kwargs: None)
        self.telemetry = SafeTelemetryContext(telemetry)
        self.checkpoint_store = checkpoint_store
        self.run_id, self.user_id = run_id, user_id
        self.provider = self.model = None
        self.output_tokens = 0
        self.retry_count = 0

    def set_model_metadata(self, *, provider=None, model=None):
        self.raise_if_cancelled()
        self.provider = provider if provider in {"openai", "custom", "mock"} else None
        # Configuration identifiers only; credentials/URLs/content have no field.
        self.model = model if isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,100}", model) and not model.startswith(("sk-", "http")) else None

    def consume_output(self, text):
        self.raise_if_cancelled()
        self.output_tokens += self.token_estimator(text)
        if self.tokens + self.output_tokens > self.policy.budget.max_tokens:
            raise BudgetExceeded("The run token budget was exhausted.")

    def checkpoint(self, name, state):
        """Persist a recovery boundary on a best-effort basis.

        A checkpoint buys recovery, not correctness. Losing one may cost the
        ability to resume an interrupted run; it must never cost the answer, so a
        storage failure is recorded and reported instead of aborting the pipeline.
        """
        self.raise_if_cancelled()
        if self.checkpoint_store is None:
            self._report_checkpoint_unavailable(name, "no checkpoint store is configured")
            return None
        try:
            return self.checkpoint_store.save(self.run_id, self.user_id, name, state)
        except Exception as error:
            self._report_checkpoint_unavailable(name, type(error).__name__)
            return None

    def _report_checkpoint_unavailable(self, name, error_type):
        try:
            self.record("STEP_FAILED", self, {"error_code": "CHECKPOINT_UNAVAILABLE",
                                              "error_type": "internal", "error_class": error_type})
        except Exception:
            # Diagnostics must never be able to fail the run either.
            pass

    def consume_input(self, text):
        self.raise_if_cancelled()
        self.input_chars += len(text)
        self.tokens += self.token_estimator(text)
        if self.input_chars > self.policy.budget.max_input_chars or self.tokens + self.output_tokens > self.policy.budget.max_tokens:
            raise BudgetExceeded("The run input budget was exhausted.")
    def consume_context(self, text):
        """Model context consumes tokens; the character ceiling is for the question."""
        self.raise_if_cancelled()
        self.tokens += self.token_estimator(text)
        if self.tokens + self.output_tokens > self.policy.budget.max_tokens:
            raise BudgetExceeded("The run token budget was exhausted.")
    def raise_if_cancelled(self):
        if self.cancel_event.is_set():
            raise RunCancelled("The run was cancelled.")
        if self.clock() >= self.deadline_at:
            raise RunTimedOut("The run deadline was exceeded.")
    def remaining_seconds(self):
        self.raise_if_cancelled()
        return self.deadline_at - self.clock()
    async def call(self, operation):
        """Bound sync work without letting executor shutdown delay the caller.

        Python cannot kill running threads. Slots remain occupied until work exits;
        late results are discarded and never advance the workflow.
        """
        self.raise_if_cancelled()
        token = remaining_model_timeout.set(self.remaining_seconds)
        try:
            if inspect.iscoroutinefunction(operation):
                return await self.wait(operation())
            slots = _SYNC_SLOTS
            while not slots.acquire(blocking=False):
                await self.wait(asyncio.sleep(0.005))
            loop = asyncio.get_running_loop()
            future = loop.create_future()
            copied = copy_context()

            def publish(value, error):
                if future.done():
                    if inspect.iscoroutine(value):
                        value.close()
                elif error is not None:
                    future.set_exception(error)
                else:
                    future.set_result(value)

            def worker():
                value = error = None
                try:
                    copied.run(self.raise_if_cancelled)
                    value = copied.run(operation)
                except BaseException as caught:
                    error = caught
                finally:
                    slots.release()
                try:
                    loop.call_soon_threadsafe(publish, value, error)
                except RuntimeError:
                    if inspect.iscoroutine(value):
                        value.close()

            try:
                Thread(target=worker, name="fitlife-agent-operation", daemon=True).start()
            except BaseException:
                slots.release()
                raise
            value = await self.wait(future)
            return await self.wait(value) if inspect.isawaitable(value) else value
        finally:
            remaining_model_timeout.reset(token)
    async def step(self, name, operation):
        self.current_step = name
        async with self.telemetry.span("fitlife.agent.step", {"step": name}):
            if name in {"safety_reviewer", "output_guard"}:
                async with self.telemetry.span("fitlife.safety.review", {"step": name}):
                    result = await self._invoke(name, operation, "safe")
            else:
                result = await self._invoke(name, operation, "safe")
        self.completed_steps.append(name)
        return result
    async def tool(self, name, replay: Literal["safe","never"], operation):
        async with self.telemetry.span("fitlife.agent.tool", {"step": name}):
            result = await self._invoke(name, operation, replay, is_tool=True)
        self.completed_tools.append(name)
        return result
    async def wait(self, awaitable):
        task = asyncio.ensure_future(awaitable)
        consumed = False
        try:
            while not task.done():
                self.raise_if_cancelled()
                await asyncio.wait({task}, timeout=min(0.005, max(0, self.deadline_at - self.clock())))
            self.raise_if_cancelled()
            consumed = True
            return task.result()
        finally:
            if not task.done():
                task.cancel()
            elif not consumed and not task.cancelled() and task.exception() is None:
                value = task.result()
                if inspect.iscoroutine(value):
                    value.close()
            task.add_done_callback(_consume_completion)
    async def _invoke(self, name, operation, replay, is_tool=False):
        limit = self.policy.retry.max_attempts if replay == "safe" else 1
        known_tools = {"plan_route_model", "write_answer_model", "safety_review_model", "load_profile", "analyze_meals", "analyze_workouts", "retrieve_knowledge", "generate_weekly_report", "generate_next_week_plan", "validate_plan"}
        metadata = {"tool": name if name in known_tools else "other"} if is_tool else {}
        for attempt in range(1, limit + 1):
            self.attempt = attempt
            self.raise_if_cancelled()
            if is_tool:
                self.tool_calls += 1
                if self.tool_calls > self.policy.budget.max_tool_calls:
                    raise BudgetExceeded("The tool-call budget was exhausted.")
                if name.endswith("_model"):
                    self.model_calls += 1
                    if self.model_calls > self.policy.budget.max_model_calls:
                        raise BudgetExceeded("The model-call budget was exhausted.")
            try:
                self.record("TOOL_STARTED" if is_tool else "STEP_STARTED", self, metadata)
                if is_tool and name.endswith("_model"):
                    async with self.telemetry.span("fitlife.ai.request", {"attempt": attempt}):
                        result = await self.call(operation)
                else:
                    result = await self.call(operation)
                self.raise_if_cancelled()
                self.record("TOOL_FINISHED" if is_tool else "STEP_SUCCEEDED", self, {**metadata, "outcome": "succeeded"})
                return result
            except (RunCancelled, RunTimedOut, BudgetExceeded):
                self.record("TOOL_FINISHED" if is_tool else "STEP_FAILED", self, {**metadata, "outcome": "failed"})
                raise
            except Exception as error:
                failure=classify_failure(error, stage=name, attempt=attempt)
                self.record("TOOL_FINISHED" if is_tool else "STEP_FAILED", self, {**metadata, "outcome": "failed"})
                if attempt >= limit or getattr(error,"_fitlife_no_replay",False) or decide_disposition(failure) is not Disposition.RETRY:
                    try:
                        setattr(error, "_fitlife_no_replay", True)
                    except Exception:
                        pass
                    raise
                delay=self.policy.retry.delay_seconds(attempt, retry_after=failure.retry_after_seconds, random_value=self.random_value())
                self.raise_if_cancelled()
                if delay >= self.deadline_at - self.clock():
                    raise RunTimedOut("The run deadline was exceeded.") from None
                self.record("STEP_RETRY_SCHEDULED", self, {"delay_ms": delay * 1000})
                self.retry_count += 1
                async with self.telemetry.span("fitlife.agent.retry_wait", {"attempt": attempt, "delay_ms": delay * 1000}):
                    await self.call(lambda: self.sleeper(delay))
                self.raise_if_cancelled()
        raise AssertionError("unreachable")

class AgentRuntime:
    def __init__(self, *, policy=None, clock=time.monotonic, sleeper=_sleep, random_value=random_module.random, token_estimator=None,
                 repository=None, checkpoint_store=None, telemetry=None, resolver=None, limiter=None):
        self.policy = policy or RuntimePolicy()
        self.resolver = resolver or ConfigurationResolver(environment=asdict(self.policy))
        self.limiter = limiter or ProcessRateLimiter(clock=clock)
        self.clock = clock
        self.sleeper = sleeper
        self.random_value = random_value
        self.token_estimator = token_estimator
        self._runs = {}
        self._cancellations = {}
        self._lock = RLock()
        self.repository = repository or MemoryRunRepository()
        self.checkpoint_store = checkpoint_store or (MemoryCheckpointStore(self.repository) if isinstance(self.repository, MemoryRunRepository) else None)
        self.telemetry = SafeTelemetryContext(telemetry)
    @property
    def active_run_ids(self):
        with self._lock:
            return tuple(k for k, v in self._runs.items() if v.status in ("accepted", "running"))
    async def execute(self, command: AgentCommand, workflow: AgentWorkflow):
        async with self.telemetry.span("fitlife.agent.run", {"operation": command.operation, "policy_version": "default-v1"}) as span:
            return await self._execute(command, workflow, span)

    async def _execute(self, command: AgentCommand, workflow: AgentWorkflow, span):
        run_id = uuid4().hex
        request_id = command.request_id or uuid4().hex
        event = Event()
        with self._lock:
            self._cancellations[run_id] = event
        now = datetime.now(timezone.utc)
        config_error = None
        try:
            config = self.resolver.resolve(command.operation, command.user_id, getattr(command, "request_overrides", None))
        except Exception as error:
            config = EffectiveRunConfig()
            config_error = ApplicationError(code="CONFIGURATION_INVALID", message="The requested Agent configuration is invalid.",
                                            status_code=422, processing_mode="agent") if isinstance(error, ValueError) else error
        policy = config.policy
        lease = None
        context=RuntimeContext(policy=policy,clock=self.clock,sleeper=self.sleeper,random_value=self.random_value,token_estimator=self.token_estimator,cancel_event=event,deadline_at=self.clock()+policy.deadline_seconds,
                               record=lambda kind, ctx, payload=None: self._record(run_id, kind, ctx, payload),
                               telemetry=self.telemetry, checkpoint_store=self.checkpoint_store, run_id=run_id, user_id=command.user_id)
        context.effective_config = config
        span.set_attributes({"policy_version": f"policy-{config.revision}"})
        try:
            with self._lock:
                self._runs[run_id] = self.repository.create(AgentRunSnapshot(
                    run_id, request_id, command.user_id, command.operation, "accepted",
                    created_at=now.isoformat(), deadline_at=(now + timedelta(seconds=policy.deadline_seconds)).isoformat(),
                    policy_version=f"policy-{config.revision}",
                    policy_snapshot_json=RunPolicySnapshot(revision=config.revision, policy=policy).model_dump_json()))
                self._runs[run_id] = self.repository.update(replace(self._runs[run_id], status="running", started_at=utc_now()), "RUN_STARTED")
            if config_error:
                raise config_error
            lease = self.limiter.acquire(command.user_id, policy.rate_limit)
            def guard():
                try:
                    decision = check_input(command.question)
                except SafetyRefusal as error:
                    self._safety_event(context, error.decision)
                    raise
                self._safety_event(context, decision)
            await context.step("input_guard", guard)
            context.consume_input(command.question)
            command_payload = json.dumps({"surface": command.surface,
                "context_date": command.context_date, "initial_tool_results": command.initial_tool_results,
                "initial_tool_calls": command.initial_tool_calls}, ensure_ascii=False, default=str)
            context.consume_context(command_payload)
            result=replace((await context.call(lambda: workflow.execute(command,context))).with_request_id(),request_id=request_id,run_id=run_id)
            def review():
                try:
                    answer, decision = review_output(command.question, result.answer_markdown)
                except SafetyRefusal as error:
                    self._safety_event(context, error.decision)
                    raise
                self._safety_event(context, decision)
                # Rewrites cannot carry an unchecked auxiliary model payload.
                return replace(result, answer_markdown=answer,
                               tool_results={} if decision.outcome != "allow" else result.tool_results,
                               sources=() if decision.outcome != "allow" else result.sources)
            result = await context.step("output_guard", review)
            result = await context.step("public_result_projector", lambda: result)
            context.raise_if_cancelled()
            with self._lock:
                self._finish(run_id, "succeeded", context)
                self._evict_completed(policy.max_completed_runs)
            return AgentOutcome(run_id,request_id,"succeeded",result)
        except asyncio.CancelledError:
            event.set()
            error = RunCancelled("The run was cancelled.", run_id=run_id, request_id=request_id)
            with self._lock:
                self._finish(run_id, "cancelled", context, error)
                self._evict_completed(policy.max_completed_runs)
            raise error from None
        except Exception as error:
            status="cancelled" if isinstance(error,RunCancelled) else "timed_out" if isinstance(error,RunTimedOut) else "failed"
            with self._lock:
                if run_id in self._runs:
                    self._finish(run_id, status, context, error)
            with self._lock:
                self._evict_completed(policy.max_completed_runs)
            try:
                error.run_id = run_id
                error.request_id = request_id
            except Exception:
                pass
            raise
        finally:
            if lease is not None:
                lease.release()
            span.set_attributes({"input_tokens": context.tokens, "output_tokens": context.output_tokens,
                                 "tool_calls": context.tool_calls, "model_calls": context.model_calls,
                                 "retry_count": context.retry_count})
            event.set()
            with self._lock:
                self._cancellations.pop(run_id, None)
                run = self._runs.get(run_id)
                if run is not None and run.status not in TERMINAL_STATUSES:
                    # Storage failure cannot leave an executable process entry.
                    self._runs.pop(run_id, None)
    @staticmethod
    def _safety_event(context, decision):
        context.record("SAFETY_DECIDED", context, {"outcome": decision.outcome,
                       "risk_category": decision.risk_category, "rule_version": SAFETY_RULE_VERSION})
    async def get_status(self,run_id,user_id):
        return self.repository.get(run_id, user_id)
    async def cancel(self,run_id,user_id):
        with self._lock:
            try:
                run = self.repository.get(run_id, user_id)
            except KeyError:
                return CancelResult(run_id, False, "not_found")
            event = self._cancellations.get(run_id)
            if event is None or run.status in TERMINAL_STATUSES:
                return CancelResult(run_id, False, run.status)
            self._runs[run_id] = self.repository.update(self._runs[run_id], "RUN_CANCEL_REQUESTED")
            event.set()
        return CancelResult(run_id,True,"cancellation_requested")

    def _record(self, run_id, kind, context, payload=None):
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or run.status in TERMINAL_STATUSES:
                return
            self._runs[run_id] = self.repository.update(replace(run,
                current_step=context.current_step, attempt=context.attempt,
                input_chars=context.input_chars, input_tokens=context.tokens, output_tokens=context.output_tokens,
                provider=context.provider, model=context.model, tool_calls=context.tool_calls), kind, payload)

    def _finish(self, run_id, status, context, error=None):
        run = self._runs[run_id]
        if run.status in TERMINAL_STATUSES:
            return
        code = None
        if error is not None:
            code = error.code if isinstance(error, RuntimeControlError) else classify_failure(error, stage=context.current_step or "runtime", attempt=context.attempt).code
            code = code if code in ERROR_CODES else "INTERNAL_ERROR"
        internal_error_id = uuid4().hex if error else None
        proposed = replace(run,
            status=status, current_step=context.current_step, attempt=context.attempt,
            input_chars=context.input_chars, input_tokens=context.tokens, output_tokens=context.output_tokens, tool_calls=context.tool_calls,
            provider=context.provider, model=context.model,
            public_error_code=code, internal_error_id=internal_error_id,
            failure_stage=context.current_step if error else None, finished_at=utc_now())
        payload = {"error_code": code, "internal_error_id": internal_error_id} if error else {}
        try:
            self._runs[run_id] = self.repository.update(proposed, "RUN_" + status.upper(), payload)
        except Exception as storage_error:
            storage_error.run_id = run_id
            storage_error.request_id = run.request_id
            if error is not None:
                storage_error.finalization_error = error
            raise
    def execute_sync(self,command,workflow):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.execute(command, workflow))
        result = []
        failure = []
        def bridge():
            try:
                result.append(asyncio.run(self.execute(command, workflow)))
            except BaseException as error:
                failure.append(error)
        thread = Thread(target=bridge, name="fitlife-agent-sync-bridge")
        thread.start()
        thread.join()
        if failure:
            raise failure[0]
        return result[0]

    def _evict_completed(self, max_completed_runs):
        terminal = [run_id for run_id, run in self._runs.items() if run.status not in ("accepted", "running")]
        for run_id in terminal[:-max_completed_runs] if max_completed_runs else terminal:
            self._runs.pop(run_id, None)
