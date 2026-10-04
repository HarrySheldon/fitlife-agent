# Agent Runtime

This guide describes the explicit Python runtime in `backend/agent`. Business
calculations and writes remain deterministic application use cases. The runtime
is not a graph engine, distributed scheduler or conversational session store.

## Modules and ownership

```text
HTTP / Python entry points
  -> infrastructure.agent_runtime.factory.get_agent_runtime()
     -> AgentRuntime: admission, guards, deadline, retry, IDs, state
        -> FitLifeWorkflow / StructuredSuggestionWorkflow
           -> ModelGateway / read-only tools / deterministic validation
     -> AgentRunRepository: authoritative status + ordered events
     -> CheckpointStore: validated planner recovery boundary
     -> TelemetryContext: optional, content-free diagnostics

configuration.resolver -> immutable policy/revision for each execution
configuration.store   -> atomic last-known-good policy publication
```

The factory lazily creates one runtime per effective data directory, using
`agent_runtime.sqlite3`. It does not share the business database migration
sequence. Tests inject memory adapters; production uses SQLite run and checkpoint
adapters. `CurrentAgentRuntime` is a forwarding compatibility handle, not another
runtime. Model settings are resolved once inside bounded workflow execution;
policy resolution does not read model connection files or decrypt secrets.

| Concern | Implementation |
| --- | --- |
| Commands, results, status and public errors | `backend/agent/contracts.py` |
| Run execution, bounded calls and control | `backend/agent/runtime.py` |
| Fitness workflow and result projection | `backend/agent/workflow.py` |
| Plan/Smart Entry structured suggestions | `backend/agent/structured_workflow.py` |
| Classification and retry calculation | `backend/agent/failures.py`, `policy.py` |
| Mandatory content screening | `backend/agent/safety.py` |
| Persistence protocols and payload validation | `backend/agent/persistence.py` |
| Planner checkpoint schema | `backend/agent/checkpoints.py` |
| Policy validation, resolution and diagnostics | `backend/configuration/` |
| SQLite, memory and process admission adapters | `backend/infrastructure/agent_runtime/` |

## Public Python interfaces

The following signatures describe the supported execution surface. Dependencies
are constructor-injected for tests; callers do not need to operate repositories,
provider SDKs or telemetry adapters to execute a workflow.

```python
class AgentRuntime:
    async def execute(self, command: AgentCommand,
                      workflow: AgentWorkflow) -> AgentOutcome: ...
    def execute_sync(self, command: AgentCommand,
                     workflow: AgentWorkflow) -> AgentOutcome: ...
    async def get_status(self, run_id: str,
                         user_id: str | None) -> AgentRunSnapshot: ...
    async def cancel(self, run_id: str,
                     user_id: str | None) -> CancelResult: ...

class AgentWorkflow(Protocol):
    async def execute(self, command: AgentCommand,
                      context: RuntimeContext) -> AgentResult: ...

class RuntimeContext:
    async def step(self, name: str,
                   operation: Callable[[], Awaitable[T] | T]) -> T: ...
    async def tool(self, name: str, replay: Literal["safe", "never"],
                   operation: Callable[[], Awaitable[T] | T]) -> T: ...
    async def call(self, operation: Callable[[], Awaitable[T] | T]) -> T: ...
    async def wait(self, awaitable: Awaitable[T]) -> T: ...
    def checkpoint(self, name: str, state: Mapping[str, object]) -> Checkpoint: ...
    def raise_if_cancelled(self) -> None: ...
    def remaining_seconds(self) -> float: ...
    def consume_input(self, text: str) -> None: ...
    def consume_context(self, text: str) -> None: ...
    def consume_output(self, text: str) -> None: ...
    def set_model_metadata(self, *, provider=None, model=None) -> None: ...
```

Every model request uses a named `tool()` ending in `_model` inside a workflow
step, so attempts count against both tool and model budgets. `call()` is the
bounded execution primitive, not a substitute for named model/tool accounting.
Only explicitly replay-safe tools may retry. New stateful tools must use
`replay="never"`; formal record writes do not belong in these workflows.

`execute()` returns an outcome only on success. Failures raise the original
application/control exception (or an internal exception), annotated with run and
request IDs. Status lookup enforces exact owner matching and raises `KeyError`
for missing or other-owner runs. Cancellation returns `not_found` for inaccessible
runs, preserves terminal states, and requests cancellation only for locally active
runs. Anonymous ownership is `None`, not a separate authenticated identity.

Status/cancel are Python interfaces, not HTTP control routes. Requests currently
execute in-process until completion; there is no background queue, restart replay
or cross-process cancellation. `execute_sync()` bridges synchronous API callers,
including a caller already running an event loop.

### Command and result contracts

`AgentCommand` is a frozen dataclass containing:

| Field | Type / default |
| --- | --- |
| `operation` | `chat`, `coach_action`, `plan_review`, `weekly_review`, `evaluation`, `plan_adjustment`, `smart_entry` |
| `question`, `user_id` | `str`, `str | None` |
| `surface`, `context_date` | optional strings |
| `initial_tool_results` | mapping, empty by default |
| `initial_tool_calls` | tuple of strings, empty by default |
| `request_id` | optional caller-provided ID; generated when absent |
| `request_overrides` | optional whitelisted policy mapping |

Frozen dataclasses do not recursively freeze caller-owned mappings. Treat command
payloads as immutable for the duration of execution. HTTP schemas validate
transport input first; direct Python callers still pass through runtime guards.

`AgentResult` contains `answer_markdown`, `intent`, `trace`, `tool_results`,
`sources`, `model`, `request_id` and `run_id`. `AgentOutcome` adds the succeeded
status and wraps that result; `to_dict()` preserves the existing response shape.
Structured suggestions carry their typed object internally and return a
`StructuredAgentResult(output, model, usage, run_id, request_id)` to deterministic
callers. Plan trace / Smart Entry analysis metadata retain those IDs. No typed
model suggestion is automatically activated or confirmed.

## Workflow and safety gates

```text
Runtime: policy snapshot -> rate/concurrency admission -> input_guard
  FitLife:
    optional contextual preload -> planner -> planner checkpoint
    -> profile_loader -> data_analyzer -> optional retriever
    -> deterministic_generator -> deterministic_validator -> writer
    -> safety_reviewer -> result_projector
  Structured suggestion:
    model_configuration -> writer -> safety_reviewer -> result_projector
Runtime: output_guard -> public_result_projector -> terminal state
```

Planner flags select analysis and retrieval, never whether safety runs. Runtime
also checks returned prose, protecting custom workflow implementations. Coach
preloads run inside a named step, so preload failure receives IDs and a persisted
failure stage. Deterministic plan activation and Smart Entry confirmation retain
their own validation, version checks, user lifecycle guards and explicit consent.

Safety uses a conservative deterministic baseline for emergency, self-harm,
medical, extreme-diet, dangerous-training and explicit out-of-scope requests.
It is not a clinically validated or universal natural-language classifier. Code
hard rules cannot be disabled by policy or relaxed by an extra reviewer.

`SafetyDecision` is strict, frozen and revalidated at the extension boundary:
`outcome` is `allow | rewrite | refuse`; `risk_category` and `violations` use
controlled risk codes; `required_disclaimer` is absent or one of the controlled
English/Chinese lifestyle notices. Invalid/unavailable additional review returns
a preset safe notice for low-risk prose, never the unreviewed draft. High-risk
input is refused before model resolution. Unsafe structured output is refused,
not coerced into a seemingly valid plan or nutrition object. Safety events contain
only category, outcome and rule version, never the question, draft or violations
text. Public messages support English and Simplified Chinese.

## Persistence, recovery and lifecycle

The database uses runtime schema version 1 and three logically separate stores:

- `agent_runs`: `id`, unique `request_id`, owner, operation, status, current step,
  attempt, creation/start/deadline/finish timestamps, policy version/snapshot,
  actual provider/model, input characters, estimated input/output tokens, tool
  calls, public error code, internal error ID, failure stage and optimistic version.
- `agent_run_events`: `(run_id, seq)` primary key, type, step, attempt, timestamp
  and allowlisted JSON payload. Creation inserts `RUN_ACCEPTED`; state changes
  and their append-only events commit in the same SQLite transaction.
- `agent_checkpoints`: separately validated workflow boundary state. Checkpoints
  are neither event logs nor public traces.

Lifecycle: `accepted -> running -> succeeded | failed | cancelled | timed_out`.
Terminal rows are immutable. Updates require the expected optimistic version;
stale writes raise `VersionConflict`. Event types include run acceptance/start/
terminal states, step start/retry/success/failure, tool start/finish, safety
decisions and cancellation requests. Unsupported schema versions are rejected
before schema writes. Connections close after each operation.

The effective `max_completed_runs` bounds only the runtime's completed in-memory
cache. Eviction never deletes SQLite history. Database retention/backups remain
an operator concern. SQLite history survives process restart, but there is no
automatic restart recovery, worker lease, distributed ownership or replay service.

After the planner, the workflow saves a strict versioned checkpoint:

```json
{"schema_version":1,"next_step":"profile_loader","route":{"intent":"knowledge_qa","needs_meal_analysis":false,"needs_workout_analysis":false,"needs_retrieval":true,"needs_plan":false,"needs_report":false}}
```

Use `restore_planner_state()` or `rebuild_state_after_planner(original_command,
checkpoint, context_metadata=...)` to reconstruct only the validated routing
boundary. Reload deterministic data; never treat arbitrary saved state, public
trace or a completed/attempt marker as a recoverable workflow. These helpers do
not themselves execute a resumed run or bypass input/output guards. The original
command is intentionally not persisted in checkpoints.

## Retry, deadline, cancellation and budgets

Default retry is three retries after the initial attempt (four total), exponential
backoff with jitter, capped delay and bounded provider `Retry-After`. Both OpenAI
protocol adapters set SDK `max_retries=0`. Connection failures, 408, explicitly
recoverable 409, transient 429 and selected 5xx are retryable; credentials, invalid
input/model, exhausted quota/billing and safety refusals are not. An exhausted
nested tool cannot cause its parent step to replay the tool again.

All waits/attempts share one monotonic deadline. Cancellation is checked before
and after work and during backoff. Both model protocols receive remaining timeout
through the model-call context. There are 16 bounded daemon worker slots for sync
operations. A timed-out sync operation may continue remotely or in its thread:
Python cannot kill it. Its slot remains occupied until it exits, and its late
result cannot advance run state or produce business writes. Async operations must
cooperate with cancellation; this is not process isolation. Synchronous repository
transactions are short local operations, not a hard real-time storage guarantee.

Default limits are 8,000 question characters, 32,000 estimated tokens, 16 model
attempts, 32 tool attempts and a 60-second run deadline. Context and output count
toward tokens; only the question counts toward the character ceiling. The default
token estimator is approximately one token per four characters, not provider
billing usage. Retries consume model/tool budgets too.

The shared process limiter defaults to 60 requests/minute and four concurrent
runs per user; anonymous callers share a stricter 10/minute, one-concurrent bucket.
It bounds buckets and does not evict active/unexpired buckets to evade limits.
Leases release once on every completion path. Multiple server processes have
independent limiters; Redis/distributed admission is not implemented.

## Configuration

Deployment `Settings` stays compatible with the existing environment loader.
Dynamic execution policies use strict Pydantic models with unknown fields rejected,
finite values and immutable nested objects. Legacy `backend.agent.policy`
dataclasses remain convenient constructor inputs for earlier callers; resolution
produces the validated configuration model.

Priority is code safety ceilings, administrator emergency restrictions,
whitelisted request overrides, permitted user settings, route policy, deployment
environment and defaults. User model connections remain in the existing secure
connection subsystem, not runtime policy or diagnostics. There are currently no
user-configurable runtime budget fields. Request overrides permit only deadline,
maximum tokens, model calls and tool calls; budgets cannot relax stricter lower
scope budgets or code ceilings. Emergency publication can only tighten effective
limits. No scope offers a safety-disable flag.

`ConfigurationResolver.resolve(operation, user_id, request_overrides=None)` returns
an immutable `EffectiveRunConfig(revision, policy)`. `MemoryPolicyStore.publish`
validates the complete candidate (omitted fields receive safe defaults), then
atomically publishes a new monotonically increasing revision. Validation failure
raises a generic rejection and retains the last good revision; bounded operator
diagnostics contain only a code and revision. In-flight runs retain their original
snapshot, even while another request uses a newly published policy. Publication
is an in-process administrative Python interface, not a public HTTP endpoint.

The deployment environment field is `AGENT_RUNTIME_POLICY`, a JSON policy object.
For example, from PowerShell before starting the backend:

```powershell
$env:AGENT_RUNTIME_POLICY = '{"deadline_seconds":30.0,"rate_limit":{"requests_per_minute":30}}'
```

For programmatic publication:

```python
from backend.infrastructure.agent_runtime.factory import get_agent_runtime

runtime = get_agent_runtime()
revision = runtime.resolver.store.publish({"deadline_seconds": 20.0})
# No user connection, endpoint or credential is part of this object.
```

A persisted snapshot is JSON with `revision` and the full validated `policy`.
It contains retry, budget, deadline, retention, rate and evaluation limits, never
an endpoint or API key. `policy_version` is `policy-<revision>`. Actual provider and
model are recorded separately when the bounded workflow resolves its gateway;
a provider-reported model version can replace a configured alias in metadata
without rebinding the connection.

## Errors and diagnostics

The internal `RuntimeFailure` holds classification, stage, disposition inputs,
attempt, provider status, bounded retry delay and optional cause. It is never
serialized. HTTP errors use `PublicError`/compatible `ApiError` fields: `code`,
localized `message`, optional `action`, `retryable`, optional `retry_after_ms`,
`request_id`, optional `run_id`. Middleware also returns `x-request-id`.
Validation failures before Agent acceptance have no run; runtime failures retain
run identity. If runtime storage itself is unavailable, an ID is still attached
to the exception where possible, but successful persistence cannot be promised.

| Failure | Handling / public code |
| --- | --- |
| Transient provider/network | bounded retry, then safe model error |
| Missing/disabled model connection | user action; `AI_NOT_CONFIGURED` / `AI_DISABLED` |
| Credentials/model selection | no retry; `MODEL_AUTH_FAILED` / `MODEL_NOT_FOUND` |
| Provider quota/billing | no retry; `MODEL_QUOTA_EXHAUSTED` |
| Unsupported provider response | `MODEL_PROTOCOL_ERROR` |
| Local admission | 429, `AGENT_RATE_LIMITED`, safe retry delay |
| Invalid runtime override | 422, `CONFIGURATION_INVALID` |
| Safety refusal | 422, `SAFETY_REFUSAL` |
| Run deadline | 504, `RUN_TIMED_OUT` |
| Run budget | 429, `RUN_BUDGET_EXCEEDED` |
| Cancellation | 409, `RUN_CANCELLED` |
| Credential-store availability | generic `CREDENTIAL_STORE_UNAVAILABLE` |
| Unknown failure | 500, `INTERNAL_ERROR`; no original exception text |

Repository events carry a safe error code, internal error ID and failure stage.
Unknown classifications become `INTERNAL_ERROR`. Raw causes are not durably
stored; the internal ID correlates sanitized run/event diagnostics, not a
persisted stack trace. Do not expose provider bodies, filesystem paths, SQL,
environment-variable details, health inputs, prompts or secrets in public errors.

Telemetry is optional and separate from authority. `NoopTelemetryContext` is the
default; `InMemoryTelemetryContext` records isolated parent/child spans. Safe
wrapping filters attributes, strips exception content and ignores adapter failures
without swallowing business failures. Spans cover run, step, tool, model request,
retry wait and safety review, recording timing, counts, outcome and policy revision.
There is no production export adapter in this change.

## Evaluation

Evaluation explicitly selects `execution_mode="mock"` or `"live"`; the default is
Live for compatibility. Mock uses the deterministic planner/writer adapter inside
the same runtime workflow, guards and accounting. It does not call a provider and
is never selected automatically when a Live case fails. Mock scores test local
plumbing and deterministic behavior, not live model quality.

```powershell
.venv\Scripts\python.exe scripts\run_eval.py --mode mock --limit 3
.venv\Scripts\python.exe scripts\run_eval.py --mode live --limit 3
```

The CLI's Live mode uses the explicitly enabled unauthenticated deployment
connection. For a signed-in user's connection, send an authenticated
`POST /eval/run` request with an optional body such as:

```json
{"limit":3,"execution_mode":"live"}
```

Python callers use `run_evaluation(limit=None, request_id=None, user_id=None,
execution_mode="live")`. Live gateway resolution and model execution are bounded
inside each case's runtime; invalid credentials become ordinary case errors with
run identity, not a silent switch to Mock.

The entire dataset is validated before slicing by `limit`; its canonical validated
content determines `dataset_hash`. Batch policy/case limits are checked before
starting cases. Batch admission consumes one request-rate slot but no concurrent
run slot; each started case has normal independent admission. Default batch limits
are 100 cases, 1,600 reserved model calls and 3,200,000 reserved estimated tokens.
These are `policy.evaluation` fields and can be tightened by deployment/emergency
policy. Each case reserves its whole run model/token allowance before launch;
unused allowance is not refunded because timed-out workers can still be running.
This conservative reservation is not actual billing usage. Rate limits can reject
cases even when reservation budget remains, including the shared anonymous limit.

| Case result | Batch behavior |
| --- | --- |
| Checks all pass / some fail | `case_status=passed` / `failed`, continue |
| Provider, configuration or other case exception | `error`, normalized code, continue |
| Runtime deadline | `timed_out`, continue |
| Insufficient remaining batch reservation | `skipped`; do not start a new run |

Dataset/preparation or result-storage failures can fail the batch. Runtime/scoring
case failures must not erase completed case results or prevent later cases from
running. Each started case has a new `request_id` and runtime `run_id`, linked to
the batch's request/report ID. Skipped cases have no runtime row, `run_id=null`
and no execution timestamps. The batch `run_id` identifies an evaluation report,
not an `agent_runs` row or background task.

Reports include execution mode, provider/model, prompt version, policy version,
dataset hash, start/finish times, case status and safe error code. Started cases
use their actual runtime snapshot for model/policy provenance; batch metadata
describes batch preparation, not a substitute for per-case facts. A policy reload
can therefore produce different case revisions within the same batch.
`provenance_status` distinguishes available snapshots from unavailable metadata;
skipped cases also have unavailable provenance. A run-storage failure must not abort later cases:
the affected case remains an error, keeps its correlation ID when available,
and does not invent a policy/provider/model snapshot. Failed snapshot lookup also
prevents a successful model response from being reported as a verified pass.

Aggregate/group metrics and boolean named checks remain available to the UI.
Privacy changes are intentional: `case_id` is opaque; `display_label` and the
legacy `question` display field contain only `Case N`. Raw questions, model
answers, arbitrary traces, expected/observed keyword text and provider exceptions
are not written. Check reasons are static, tools are allowlisted, and retrieval
requirements are represented without health-text excerpts. Failed/skipped cases
remain in the report and count as non-passing in aggregate rates.

Each batch writes its own `data_dir/eval_runs/<batch_run_id>/eval_results.json`
and `.md`. Compatibility `data_dir/eval_results.json` / `.md` files contain the
latest report, replaced atomically per file; they are not a transactional
multi-file pair. Use the immutable batch directory for durable correlation.
Tests redirect both directories to temporary storage and must never overwrite
the installation's reports. Live evaluation may incur provider charges; tests and
offline verification must explicitly use Mock or injected fake gateways.

## Tests and operation

From a standard checkout with its project interpreter:

```powershell
.venv\Scripts\python.exe -m pytest --version
.venv\Scripts\python.exe -m pytest backend/tests -q --basetemp=.tmp/runtime-tests-unique
```

From this refactor worktree, use the main checkout's environment explicitly:

```powershell
& 'D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe' -m pytest backend/tests -q --basetemp=.tmp/runtime-worktree-tests-unique
```

Use a fresh suffix for repeated runs; this Windows environment can reject system
pytest temporary-directory access. `backend/tests/conftest.py` injects an isolated
memory runtime. Persistence tests use temporary SQLite databases; the global test
fixture redirects evaluation report paths for API tests as well as evaluator
tests. No test should request a real model or paid token.

Docker verification command (run from the intended checkout; does not imply it
has been executed during this refactor):

```powershell
docker compose run --rm --no-deps backend python -m pytest backend/tests -q --basetemp=/tmp/fitlife-runtime-tests
```

The Compose service mounts business data, so retain test isolation fixtures and
never use production data to repair a test. Back up the separate runtime database
as well when runtime audit history is required; business backup tools do not
implicitly include it. [Verification checkpoints](superpowers/plans/agent-runtime-progress.md)
record actual commands, failures, fixes and test results.

## Migration

The former LangGraph execution dependency was removed after behavioral contract
tests. The compatibility `graph.py` module still exposes existing entry names but
delegates to the factory runtime and explicit Python workflows; it contains no
LangGraph graph or second production executor. Historical plans describe the old
implementation and are not current interface documentation.

Existing successful chat/coach fields remain; error responses add safe action,
retry and identity fields. Plan/Smart Entry models now use the same runtime without
moving deterministic writes into model steps. Runtime SQLite schema and policy
publication are independent of the business schema. Endpoint safety, encrypted
credentials, explicit activation/confirmation and user lifecycle checks remain
mandatory. No automatic business-data conversion, queue, Redis service, background
worker lease or arbitrary workflow recovery was introduced by this runtime.
