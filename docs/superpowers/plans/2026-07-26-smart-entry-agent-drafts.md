# Smart Entry And Agent Analysis Drafts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse one authenticated natural-language entry into editable meal and workout candidates, use Agent analysis only for unresolved fields, and atomically confirm selected complete candidates.

**Status:** Complete
**Verified:** 2026-08-02

**Architecture:** The deterministic parser and local catalogs run first and remain fully usable without a model. A `smart_entry` row in `record_drafts` is the durable source of truth; Agent calls receive only unresolved candidate context and return strict Pydantic-validated patches. Confirmation is a separate SQLite transaction and never occurs inside an Agent or LangGraph node.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, SQLite/FTS5, OpenAI-compatible Responses and Chat Completions adapters, React 19, TypeScript, Vitest.

---

## Architecture And Open-Source Practice

- [LangGraph 1.0.8](https://github.com/langchain-ai/langgraph) documents that an interrupted node restarts from its beginning when resumed. The implementation therefore keeps side effects out of Agent execution and uses draft version checks plus idempotent confirmation.
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) recommends schema-constrained output over JSON mode. Both supported model protocols must parse a dedicated Pydantic response model.
- Existing project adapters, endpoint policy, encrypted per-user model settings, lifecycle locks, catalog visibility, immutable snapshots, and `idempotency_keys` remain authoritative.
- The Phase 5 workflow is not a general chat agent. It is a bounded application service with a narrow structured-model port.

## Confirmed Boundaries

- Deterministic parsing always runs before Agent analysis.
- A unique local catalog match may populate immutable food or exercise metadata.
- Ambiguous matches remain candidate choices; the parser does not guess.
- Agent analysis is explicit and never runs during autosave, page load, confirmation, or background work.
- Agent may estimate unknown food nutrition and exercise metadata, but may not invent completed sets, reps, load, duration, or device calories.
- Agent values remain marked as estimates with assumptions and ranges until the user explicitly accepts or edits them.
- Drafts never affect Today summaries.
- Selected candidates confirm all-or-nothing in one transaction.
- A missing, disabled, invalid, rate-limited, or timed-out model preserves the draft and returns a stable recoverable error.
- Runtime external catalog APIs, image/barcode recognition, recipe editing, and direct Agent writes remain excluded.

## File Map

**Backend domain and ports**

- Create `backend/domain/smart_entry.py`: candidate values, completeness rules, deterministic parsing helpers, and safe Agent patch merge.
- Create `backend/application/ports/smart_entry_repository.py`: draft and atomic-confirmation contracts.
- Create `backend/application/ports/structured_model_gateway.py`: generic strict structured-result contract separate from planner/writer behavior.

**Backend application and infrastructure**

- Create `backend/application/use_cases/smart_entry.py`: parse, edit, analyze, conflict, delete, and confirm orchestration.
- Create `backend/agent/smart_entry_analyzer.py`: versioned prompt and strict Pydantic Agent output.
- Create `backend/infrastructure/repositories/sqlite_smart_entry_repository.py`: owner-scoped draft persistence and one-transaction formal writes.
- Modify `backend/infrastructure/model_gateway/openai_responses.py` and `openai_chat_completions.py`: implement structured parsing with usage metadata.
- Modify `backend/application/ports/model_gateway.py`: expose the separate structured capability without coupling deterministic services to planner/writer methods.
- Create `backend/api/smart_entry.py`: authenticated routes and request/response schemas.
- Modify `backend/main.py`: register the router.

**Frontend**

- Create `frontend/src/types/smartEntry.ts`: API and editor types.
- Create `frontend/src/services/smartEntryApi.ts`: draft/analyze/confirm client.
- Create `frontend/src/hooks/useSmartEntryDraft.ts`: optimistic version and confirmation-key state.
- Create `frontend/src/components/smart-entry/SmartCandidateEditor.tsx`: selected state, issues, source labels, and explicit estimate acceptance.
- Create `frontend/src/pages/SmartEntry.tsx`: input, candidate review, Agent action, and confirmation task page.
- Modify `frontend/src/pages/Today.tsx`, `frontend/src/routes/AppRoutes.tsx`, locale resources, and `frontend/src/styles/index.css`.

## Task 1: Deterministic Candidate Domain

**Tests**

- Create `backend/tests/domain/test_smart_entry.py`.

- [x] Parse newline, semicolon, Chinese comma, and labeled meal/training segments without writing data.
- [x] Extract only explicit quantities:
  - food `g`, `ml`, or serving amounts;
  - strength `sets x reps`, optional explicit load/bodyweight;
  - cardio duration and optional explicit device calories.
- [x] Normalize full-width punctuation and case without changing the original text.
- [x] Produce stable candidate IDs from the draft parser, not from model output.
- [x] Mark unmatched or missing required fields with coded issues; ambiguous catalog resolution is covered by Task 2.
- [x] Reject Agent patches that add observed workout fields or overwrite deterministic user values.
- [x] Test Chinese and English examples, partial food data, mixed strength/cardio, and malicious Agent patches; ambiguous catalogs are covered by Task 2.
- [x] Commit `feat: parse deterministic smart entry candidates` (`4005a46`).

## Task 2: Local Catalog Resolution

**Files**

- Modify `backend/application/use_cases/smart_entry.py`.
- Reuse `SQLiteFoodCatalogRepository` and `SQLiteExerciseCatalogRepository`.
- Test `backend/tests/application/test_smart_entry.py`.

- [x] Search each normalized segment against the owner-visible local catalogs only.
- [x] Treat a case-folded exact name/alias match as unique only when exactly one visible item matches.
- [x] Return multiple candidate choices without selecting one when exact resolution is ambiguous.
- [x] Calculate food nutrition with existing deterministic portion rules.
- [x] Calculate cardio estimates only through existing deterministic workout rules; strength input has no duration/intensity and therefore receives no invented estimate.
- [x] Preserve source, license, attribution, catalog ID, and value provenance in candidate snapshots.
- [x] Re-run private catalog isolation and inactive-item exclusion under Python
  3.12/Docker. Evidence: Python 3.12.13 ran both repository isolation tests and
  the smart-entry application suite, 8 tests passing.
- [x] Commit `feat: resolve smart entry against local catalogs` (`3ff551b`).

## Task 3: Durable Smart Drafts

**Files**

- Create repository port/adapter files from the file map.
- Test `backend/tests/infrastructure/test_sqlite_smart_entry_repository.py`.

- [x] Create/get/update/delete 30-day `kind='smart_entry'` drafts.
- [x] Persist raw text, log date, parser version, candidate list, selection, issues, assumptions, and per-value source.
- [x] Require expected versions in the Repository/Application boundary; API `If-Match` is completed in Task 6.
- [x] Keep Agent status/model/prompt/usage metadata in the existing draft columns.
- [x] Find the latest owner draft by date without exposing another user's row.
- [x] Bound raw text, candidates, assumptions, and total JSON size.
- [x] Include smart drafts in existing account deletion while keeping account export excluded.
- [x] Test expiry, owner isolation, conflicts, malformed JSON defense, and lifecycle locking.
- [x] Commit `feat: persist smart entry drafts` (`ebc3cba`).

## Task 4: Strict Agent Analysis

**Files**

- Create `backend/agent/smart_entry_analyzer.py`.
- Create `backend/application/ports/structured_model_gateway.py`.
- Modify both model adapters and their tests.
- Test `backend/tests/application/test_smart_entry_analysis.py`.

- [x] Define prompt version `smart-entry-analysis-v1`.
- [x] Define strict response models with `extra='forbid'`:
  - food suggestions: concrete value, range, basis, serving assumption, and assumptions;
  - exercise suggestions: canonical name, type, primary/secondary muscles, optional MET, and assumptions;
  - no sets/reps/load/duration/device-calorie properties.
- [x] Send only the unresolved source segments, selected locale, and minimum profile fields required for deterministic post-validation.
- [x] Parse through Responses `responses.parse(..., text_format=...)` or Chat Completions `chat.completions.parse(..., response_format=...)`.
- [x] Return model ID and token usage through `StructuredModelResult`.
- [x] Run no database transaction while waiting for the model.
- [x] Merge only against the original draft version; discard stale results with `409`.
- [x] Preserve the draft and set `agent_status='failed'` on normalized model errors.
- [x] Require explicit user acceptance before an Agent estimate becomes confirmable.
- [x] Test no configuration, timeout, authentication, rate limit, invalid structure, extra fields, stale results, and successful merge; disabled model uses the same injected `ApplicationError` path as existing model settings tests.
- [x] Commit `feat: analyze unresolved smart entry fields` (`4e76e21`).

## Task 5: Atomic Multi-Record Confirmation

**Files**

- Implement confirmation in `sqlite_smart_entry_repository.py`.
- Test atomic behavior in its infrastructure test.

- [x] Require at least one selected candidate.
- [x] Reject selected candidates with unresolved issues or unaccepted Agent estimates.
- [x] Insert every selected meal, meal item, training session, strength exercise/set, and cardio item in one SQLite transaction.
- [x] Use `entry_method='smart_entry'` and immutable value/provenance snapshots.
- [x] Update catalog usage only for matched catalog IDs; do not silently create private catalog entries from Agent estimates.
- [x] Ensure the daily log and persistently raise planned meal count when necessary.
- [x] Store and replay one response under `(user_id, smart_entry_confirm, Idempotency-Key)`.
- [x] Delete the source draft only after every formal row and idempotency response succeed.
- [x] Force a late insert failure in tests and prove zero formal rows remain.
- [x] Test retry replay, key reuse, owner isolation, and transaction-serialized duplicate-click behavior.
- [x] Commit `feat: confirm smart entry drafts atomically` (`50b5787`).

## Task 6: Authenticated API

**Files**

- Create `backend/api/smart_entry.py`.
- Modify `backend/main.py`.
- Test `backend/tests/test_smart_entry_api.py`.

- [x] Add:
  - `POST /api/v1/smart-entry-drafts`;
  - `GET /api/v1/smart-entry-drafts?date=YYYY-MM-DD`;
  - `GET|PATCH|DELETE /api/v1/smart-entry-drafts/{id}`;
  - `POST /api/v1/smart-entry-drafts/{id}/analyze`;
  - `POST /api/v1/smart-entry-drafts/{id}/confirm`.
- [x] Require authentication on every route.
- [x] Use `If-Match` for update/analyze/confirm and UUID `Idempotency-Key` for confirmation.
- [x] Return `processing_mode='deterministic'` for parse/edit/confirm and `processing_mode='agent'` only for analyze.
- [x] Localize stable errors while preserving codes.
- [x] Deprecate authenticated writes through `/calendar/agent-entry`; it must not create CSV records for signed-in users.
- [x] Test OpenAPI contracts, auth, validation, owner isolation, conflicts, and processing mode.
- [x] Commit `feat: expose smart entry draft workflow` (`e6374ab`).

## Task 7: Smart Entry Task Page

**Files**

- Create frontend files from the file map.
- Test `frontend/src/pages/SmartEntry.test.tsx`, `frontend/src/hooks/useSmartEntryDraft.test.tsx`, and `frontend/src/services/smartEntryApi.test.ts`.

- [x] Add `/today/smart-entry?date=YYYY-MM-DD` and a Today action.
- [x] Start with a large multiline text input and deterministic Parse command.
- [x] Show each candidate as a selectable unframed row with source, issues, assumptions, and candidate choices.
- [x] Provide labeled multiline fields rather than one compressed row.
- [x] Keep unknown numeric values empty.
- [x] Enable Analyze only when unresolved candidates exist and only after explicit click.
- [x] Preserve deterministic candidates and local edits when Agent analysis fails.
- [x] Require explicit acceptance of every Agent-estimated food or exercise value.
- [x] Confirm only selected complete candidates and navigate to the selected day after success.
- [x] Persist confirmation replay state across refresh with account/date-scoped recovery keys.
- [x] Add complete Chinese/English strings and responsive styles with no horizontal overflow at `390x844`.
- [x] Commit `feat: build smart entry review task` (`4a1ab67`).

## Task 8: Phase Verification

- [x] Run deterministic domain, repository, Agent-boundary, API, and frontend
  focused tests. Final focused regression evidence includes 11 Agent-analysis
  tests and 14 workout-page tests; Python 3.12 catalog/smart-entry evidence is
  8/8.
- [x] Run the complete backend suite. Final evidence: 772 tests pass with one
  known Starlette/httpx warning.
- [x] Run the complete frontend suite and `tsc -b`. Final evidence: 157 tests
  pass across 28 files and the production command completes TypeScript.
- [x] Run the production frontend build. Vite transformed 2466 modules; the
  existing chunk-size warning above 500 kB remains.
- [x] Rebuild Docker and verify backend/frontend health. Main was rebuilt on
  isolated ports 19000/14000 with both containers healthy and readiness at
  schema 3 with zero catalog or migration failures.
- [x] Desktop acceptance: parsed `燕麦 100g`, an unknown 200 g protein bowl,
  `杠铃深蹲 3x8 60kg`, and a 20-minute run. The local catalogs resolved oats,
  squat, and running; an explicit Agent action estimated the unknown food; the
  user explicitly accepted it; Today then showed 799 kcal, 116 g carbohydrate,
  49 g protein, 17 g fat, two meals, and one workout.
- [x] Mobile acceptance at `390x844` rendered the four-candidate editor in
  stacked rows with no horizontal overflow or console errors.
- [x] Reload during a lost confirmation response and verify one idempotent
  result. `useSmartEntryDraft` simulates a lost response plus refresh and reuses
  the same key; the SQLite repository replay test proves one idempotency row and
  one formal aggregate. Live browser reload kept two meals and one workout.
- [x] Verify form and catalog flows remain usable with no model configuration.
  The deterministic parse produced four editable candidates and a clear model
  configuration error without losing any draft value.
- [x] Review minimum-data model context, output schema, no direct writes,
  transaction rollback, owner isolation, and error recovery. Final review and
  regression coverage found no open Critical or Important issue.
- [x] Update README, roadmap, and this plan with exact evidence.
- [x] Commit `docs: verify workouts and smart entry`.
- [x] Push the completed Phase 5 slice; `4a1ab67` is reachable from
  `origin/main`.

## Completion Criteria

- Deterministic parsing and local catalog matching work with no model connection.
- Agent analysis is explicit, structured, minimum-context, and limited to unresolved fields.
- Agent cannot invent actual completed workout quantities.
- User edits and estimate acceptance are required before formal writes.
- Multi-record confirmation is transactional and idempotent.
- Draft, formal records, and recovery state are account-scoped.
- Today reflects confirmed smart-entry records and never draft values.
- Backend, frontend, type, build, Docker, desktop, and mobile checks have current evidence.
