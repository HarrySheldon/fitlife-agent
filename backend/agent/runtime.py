from __future__ import annotations

import asyncio
import inspect
import json
import random as random_module
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from threading import Event, RLock, Thread
from typing import Literal, TypeVar
from uuid import uuid4
from backend.agent.contracts import AgentCommand, AgentOutcome, AgentRunSnapshot, AgentWorkflow, CancelResult
from backend.agent.failures import Disposition, classify_failure, decide_disposition
from backend.agent.policy import RuntimePolicy
T = TypeVar("T")

class RuntimeControlError(Exception):
    code = "RUNTIME_ERROR"
    def __init__(self, message: str, *, run_id: str = "", request_id: str = ""):
        super().__init__(message); self.run_id = run_id; self.request_id = request_id
class RunCancelled(RuntimeControlError): code = "RUN_CANCELLED"
class RunTimedOut(RuntimeControlError): code = "RUN_TIMED_OUT"
class BudgetExceeded(RuntimeControlError): code = "RUN_BUDGET_EXCEEDED"
async def _sleep(delay: float): await asyncio.sleep(delay)

class RuntimeContext:
    def __init__(self, *, policy=None, clock=time.monotonic, sleeper=_sleep, random_value=random_module.random,
                 token_estimator=None, cancel_event=None, deadline_at=None):
        self.policy = policy or RuntimePolicy(); self.clock = clock; self.sleeper = sleeper; self.random_value = random_value
        self.token_estimator = token_estimator or (lambda text: max(1, (len(text)+3)//4)); self.cancel_event = cancel_event or Event()
        self.deadline_at = deadline_at if deadline_at is not None else clock() + self.policy.deadline_seconds
        self.completed_steps=[]; self.completed_tools=[]; self.current_step=None; self.attempt=0
        self.input_chars=self.tokens=self.model_calls=self.tool_calls=0
    def consume_input(self, text):
        self.input_chars += len(text); self.tokens += self.token_estimator(text)
        if self.input_chars > self.policy.budget.max_input_chars or self.tokens > self.policy.budget.max_tokens: raise BudgetExceeded("The run input budget was exhausted.")
    def raise_if_cancelled(self):
        if self.cancel_event.is_set(): raise RunCancelled("The run was cancelled.")
        if self.clock() >= self.deadline_at: raise RunTimedOut("The run deadline was exceeded.")
    async def step(self, name, operation):
        self.current_step=name; result=await self._invoke(name, operation, "safe"); self.completed_steps.append(name); return result
    async def tool(self, name, replay: Literal["safe","never"], operation):
        result=await self._invoke(name, operation, replay, is_tool=True); self.completed_tools.append(name); return result
    async def _invoke(self, name, operation, replay, is_tool=False):
        limit=self.policy.retry.max_attempts if replay == "safe" else 1
        for attempt in range(1, limit+1):
            self.attempt=attempt; self.raise_if_cancelled()
            if is_tool:
                self.tool_calls += 1
                if self.tool_calls > self.policy.budget.max_tool_calls: raise BudgetExceeded("The tool-call budget was exhausted.")
                if name.endswith("_model"):
                    self.model_calls += 1
                    if self.model_calls > self.policy.budget.max_model_calls: raise BudgetExceeded("The model-call budget was exhausted.")
            try:
                value=operation(); result=await value if inspect.isawaitable(value) else value; self.raise_if_cancelled(); return result
            except (RunCancelled, RunTimedOut, BudgetExceeded): raise
            except Exception as error:
                failure=classify_failure(error, stage=name, attempt=attempt)
                if attempt >= limit or getattr(error,"_fitlife_no_replay",False) or decide_disposition(failure) is not Disposition.RETRY:
                    try: setattr(error,"_fitlife_no_replay",True)
                    except Exception: pass
                    raise
                delay=self.policy.retry.delay_seconds(attempt, retry_after=failure.retry_after_seconds, random_value=self.random_value())
                self.raise_if_cancelled()
                if delay >= self.deadline_at-self.clock(): raise RunTimedOut("The run deadline was exceeded.") from None
                await self.sleeper(delay); self.raise_if_cancelled()
        raise AssertionError("unreachable")

class AgentRuntime:
    def __init__(self, *, policy=None, clock=time.monotonic, sleeper=_sleep, random_value=random_module.random, token_estimator=None):
        self.policy=policy or RuntimePolicy(); self.clock=clock; self.sleeper=sleeper; self.random_value=random_value; self.token_estimator=token_estimator
        self._runs={}; self._cancellations={}; self._lock = RLock()
    @property
    def active_run_ids(self):
        with self._lock: return tuple(k for k,v in self._runs.items() if v.status in ("accepted","running"))
    async def execute(self, command: AgentCommand, workflow: AgentWorkflow):
        run_id = uuid4().hex
        request_id = command.request_id or uuid4().hex
        event = Event()
        with self._lock:
            self._cancellations[run_id] = event
            self._runs[run_id]=AgentRunSnapshot(run_id,request_id,command.user_id,command.operation,"running")
        context=RuntimeContext(policy=self.policy,clock=self.clock,sleeper=self.sleeper,random_value=self.random_value,token_estimator=self.token_estimator,cancel_event=event,deadline_at=self.clock()+self.policy.deadline_seconds)
        try:
            command_payload = json.dumps({"question": command.question, "surface": command.surface,
                "context_date": command.context_date, "initial_tool_results": command.initial_tool_results,
                "initial_tool_calls": command.initial_tool_calls}, ensure_ascii=False, default=str)
            context.consume_input(command_payload)
            result=replace((await workflow.execute(command,context)).with_request_id(),request_id=request_id,run_id=run_id)
            with self._lock:
                self._runs[run_id]=replace(self._runs[run_id],status="succeeded",current_step=context.current_step,attempt=context.attempt)
                self._evict_completed()
            return AgentOutcome(run_id,request_id,"succeeded",result)
        except asyncio.CancelledError:
            error = RunCancelled("The run was cancelled.", run_id=run_id, request_id=request_id)
            with self._lock:
                self._runs[run_id]=replace(self._runs[run_id],status="cancelled",current_step=context.current_step,attempt=context.attempt,public_error_code=error.code)
                self._evict_completed()
            raise error from None
        except Exception as error:
            status="cancelled" if isinstance(error,RunCancelled) else "timed_out" if isinstance(error,RunTimedOut) else "failed"
            with self._lock: self._runs[run_id]=replace(self._runs[run_id],status=status,current_step=context.current_step,attempt=context.attempt,public_error_code=getattr(error,"code","INTERNAL_ERROR"))
            with self._lock: self._evict_completed()
            try: error.run_id=run_id; error.request_id=request_id
            except Exception: pass
            raise
        finally:
            with self._lock: self._cancellations.pop(run_id,None)
    async def get_status(self,run_id,user_id):
        with self._lock: run=self._runs.get(run_id)
        if run is None or run.user_id != user_id: raise KeyError(run_id)
        return run
    async def cancel(self,run_id,user_id):
        with self._lock:
            run=self._runs.get(run_id)
            event=self._cancellations.get(run_id)
        if run is None or run.user_id != user_id: return CancelResult(run_id,False,"not_found")
        if event is None: return CancelResult(run_id,False,run.status)
        event.set(); return CancelResult(run_id,True,"cancellation_requested")
    def execute_sync(self,command,workflow):
        try: asyncio.get_running_loop()
        except RuntimeError: return asyncio.run(self.execute(command,workflow))
        result=[]; failure=[]
        def bridge():
            try: result.append(asyncio.run(self.execute(command,workflow)))
            except BaseException as error: failure.append(error)
        thread=Thread(target=bridge,name="fitlife-agent-sync-bridge"); thread.start(); thread.join()
        if failure: raise failure[0]
        return result[0]

    def _evict_completed(self):
        terminal = [run_id for run_id, run in self._runs.items() if run.status not in ("accepted", "running")]
        for run_id in terminal[:-self.policy.max_completed_runs] if self.policy.max_completed_runs else terminal:
            self._runs.pop(run_id, None)
