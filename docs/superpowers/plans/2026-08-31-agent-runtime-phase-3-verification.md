# Agent Runtime Phase 3 Verification

Date: 2026-09-10

## Delivered

- Memory and SQLite authoritative run repositories with append-only ordered events. Each state update and event append share a transaction and optimistic version check; terminal states reject further mutation.
- Dedicated `data_dir/agent_runtime.sqlite3`, real run metadata columns, and independent `PRAGMA user_version=1`. Unknown schema versions are rejected before schema writes. Business database migrations remain independent. Connections close after each transaction/read.
- A lazy production factory resolves the current settings path and assembles the sole production runtime. The legacy graph handle delegates to that factory. Tests replace the factory with isolated memory runtimes; a separate integration test invokes the real factory with temporary settings and reopens its SQLite database.
- Runtime acceptance, start, live step/attempt, tool start/finish, retry, cancellation request, and terminal events. Runs retain dates, policy snapshots, provider/model identifiers, input/output estimates, tool counts, public codes, internal error IDs and failure stages. Failure events carry the same internal error ID as the snapshot.
- Repository unavailability cannot return a successful outcome. Create/start/terminal failure injection verifies correlation IDs survive storage errors. Late worker results and checkpoints cannot change terminal state.
- Separate memory/SQLite checkpoint stores persist a versioned planner recovery boundary in the real workflow: schema_version=1, next_step=profile_loader, and a strict intent/boolean PlannerRoute whitelist. `rebuild_state_after_planner` combines this validated route with the original AgentCommand; profile, analysis, retrieval and generated output must be loaded/recomputed. Only planner decisions may be reused, and future input_guard/safety_reviewer remain mandatory. Checkpoints contain no question, health, prompt, full response or free-form intent. Both stores validate on save/read and reject terminal writes and cross-user access. Legacy completion/attempt records remain readable but are not recovery inputs. This replaces the earlier metadata-only scope reduction; automatic resumption and orphan recovery remain out of scope.
- Explicit no-op/in-memory telemetry with run, step, tool, AI request and retry spans, parentage, outcome and elapsed time. Run spans receive final input/output token estimates, tool/model counts and retry counts in `finally`, including failures. Adapter entry/exit/attribute failures are isolated; business errors cannot be suppressed and their sensitive cause/traceback never reaches the adapter.
- Event payloads use field/value allowlists; non-finite metrics, arbitrary exception types, raw text and credentials are rejected. Provider/model fields contain configuration identifiers only. Token values use the existing injected estimator, not provider billing usage; writer output is estimated without persisting its text.
- Evaluation cases now get distinct request IDs and retain a batch request ID, preserving the unique run/request contract. Full evaluation case isolation remains phase 5. Evaluation tests write only to temporary output paths.
- Completed process-cache entries remain bounded while historical repository status remains queryable; the former cache-eviction test now checks both requirements.

## Verification

Interpreter: `D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe` (pytest 9.1.1 verified before tests).

TDD checkpoints: original memory contract 1 passed; SQLite contract failed for missing adapter then 2 passed; runtime repository injection failed then the live execution/controls/deadline set passed 24; terminal repository failure lost correlation IDs, then its fix passed the persistence/telemetry set (21 tests). Additional tests cover reopen/checkpoint isolation, redaction, invalid metrics, real factory/settings changes, retry telemetry parentage, and late workers.

Checkpoint correction validation (2026-09-11): `../../.venv/Scripts/python.exe -m pytest backend/tests/test_planner_checkpoint.py backend/tests/test_runtime_persistence.py backend/tests/test_agent_runtime_workflow.py -q --basetemp=.tmp/checkpoint-verification-3` passed 49 tests. The real FitLifeWorkflow writes its planner boundary to each adapter; a new store (and new SQLite repository) reads it and rebuilds validated route/state from the original command. Tests cover malformed/sensitive state, nested copy isolation, cross-user reads/writes, terminal writes and the original phase-1 direct workflow contract. An initial test incorrectly matched the allowed tool identifier `plan_route_model` as state leakage; the corrected assertion checks event payload keys directly.

Acceptance command (worktree-local temporary directory):

```powershell
& 'D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe' -m pytest backend/tests/test_runtime_persistence.py backend/tests/test_agent_runtime_controls.py backend/tests/test_runtime_deadline_waits.py backend/tests/test_runtime_quality_review.py backend/tests/test_runtime_api_errors.py backend/tests/test_agent_runtime_workflow.py backend/tests/test_runtime_telemetry.py backend/tests/test_eval.py backend/tests/test_agent_graph.py backend/tests/test_agent_planner.py backend/tests/test_chat_api.py backend/tests/test_coach_api.py backend/tests/application/test_agent_boundary.py backend/tests/test_model_settings_api.py backend/tests/application/test_model_settings.py -q --basetemp=.tmp/phase3-final-acceptance
```

Final result: **114 passed**, one existing Starlette/httpx deprecation warning, 13.31 seconds, exit code 0. The earlier Agent acceptance set passed 96 tests and the persistence/model-settings follow-up passed 36. `git diff --check` passed. No real model/network calls or paid tokens were used. The full backend suite remains a final phase-5 acceptance requirement; this phase does not claim a clean full-suite rerun.

Phase 4 configuration resolution, hard safety gates and rate limits are not included. Phase 5 owns complete evaluation isolation and final interface documentation.
