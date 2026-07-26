# Smart Entry And Agent Analysis Drafts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse one authenticated natural-language entry into editable meal and workout candidates, use Agent analysis only for unresolved fields, and atomically confirm selected complete candidates.

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

- [ ] Parse newline, semicolon, Chinese comma, and labeled meal/training segments without writing data.
- [ ] Extract only explicit quantities:
  - food `g`, `ml`, or serving amounts;
  - strength `sets x reps`, optional explicit load/bodyweight;
  - cardio duration and optional explicit device calories.
- [ ] Normalize full-width punctuation and case without changing the original text.
- [ ] Produce stable candidate IDs from the draft parser, not from model output.
- [ ] Mark unmatched, ambiguous, or missing required fields with coded issues.
- [ ] Reject Agent patches that add observed workout fields or overwrite deterministic user values.
- [ ] Test Chinese and English examples, ambiguous catalogs, partial food data, mixed strength/cardio, and malicious Agent patches.
- [ ] Commit `feat: parse deterministic smart entry candidates`.

## Task 2: Local Catalog Resolution

**Files**

- Modify `backend/application/use_cases/smart_entry.py`.
- Reuse `SQLiteFoodCatalogRepository` and `SQLiteExerciseCatalogRepository`.
- Test `backend/tests/application/test_smart_entry.py`.

- [ ] Search each normalized segment against the owner-visible local catalogs only.
- [ ] Treat a case-folded exact name/alias match as unique only when exactly one visible item matches.
- [ ] Return multiple candidate choices without selecting one when exact resolution is ambiguous.
- [ ] Calculate food nutrition with existing deterministic portion rules.
- [ ] Calculate cardio and strength estimates only through existing deterministic workout rules.
- [ ] Preserve source, license, attribution, catalog ID, and value provenance in candidate snapshots.
- [ ] Verify private catalog isolation and inactive-item exclusion.
- [ ] Commit `feat: resolve smart entry against local catalogs`.

## Task 3: Durable Smart Drafts

**Files**

- Create repository port/adapter files from the file map.
- Test `backend/tests/infrastructure/test_sqlite_smart_entry_repository.py`.

- [ ] Create/get/update/delete 30-day `kind='smart_entry'` drafts.
- [ ] Persist raw text, log date, parser version, candidate list, selection, issues, assumptions, and per-value source.
- [ ] Require `If-Match` for edits and return `409` on stale versions.
- [ ] Keep Agent status/model/prompt/usage metadata in the existing draft columns.
- [ ] Find the latest owner draft by date without exposing another user's row.
- [ ] Bound raw text, candidates, assumptions, and total JSON size.
- [ ] Include smart drafts in account deletion while keeping account export excluded.
- [ ] Test expiry, owner isolation, conflicts, malformed JSON defense, and lifecycle locking.
- [ ] Commit `feat: persist smart entry drafts`.

## Task 4: Strict Agent Analysis

**Files**

- Create `backend/agent/smart_entry_analyzer.py`.
- Create `backend/application/ports/structured_model_gateway.py`.
- Modify both model adapters and their tests.
- Test `backend/tests/application/test_smart_entry_analysis.py`.

- [ ] Define prompt version `smart-entry-analysis-v1`.
- [ ] Define strict response models with `extra='forbid'`:
  - food suggestions: concrete value, range, basis, serving assumption, and assumptions;
  - exercise suggestions: canonical name, type, primary/secondary muscles, optional MET, and assumptions;
  - no sets/reps/load/duration/device-calorie properties.
- [ ] Send only the unresolved source segments, selected locale, and minimum profile fields required for deterministic post-validation.
- [ ] Parse through Responses `responses.parse(..., text_format=...)` or Chat Completions `chat.completions.parse(..., response_format=...)`.
- [ ] Return model ID and token usage through `StructuredModelResult`.
- [ ] Run no database transaction while waiting for the model.
- [ ] Merge only against the original draft version; discard stale results with `409`.
- [ ] Preserve the draft and set `agent_status='failed'` on normalized model errors.
- [ ] Require explicit user acceptance before an Agent estimate becomes confirmable.
- [ ] Test no configuration, disabled model, timeout, authentication, rate limit, invalid structure, extra fields, stale results, and successful merge.
- [ ] Commit `feat: analyze unresolved smart entry fields`.

## Task 5: Atomic Multi-Record Confirmation

**Files**

- Implement confirmation in `sqlite_smart_entry_repository.py`.
- Test atomic behavior in its infrastructure test.

- [ ] Require at least one selected candidate.
- [ ] Reject selected candidates with unresolved issues or unaccepted Agent estimates.
- [ ] Insert every selected meal, meal item, training session, strength exercise/set, and cardio item in one SQLite transaction.
- [ ] Use `entry_method='smart_entry'` and immutable value/provenance snapshots.
- [ ] Update catalog usage only for matched catalog IDs; do not silently create private catalog entries from Agent estimates.
- [ ] Ensure the daily log and persistently raise planned meal count when necessary.
- [ ] Store and replay one response under `(user_id, smart_entry_confirm, Idempotency-Key)`.
- [ ] Delete the source draft only after every formal row and idempotency response succeed.
- [ ] Force a late insert failure in tests and prove zero formal rows remain.
- [ ] Test retry replay, key reuse, owner isolation, and duplicate-click concurrency.
- [ ] Commit `feat: confirm smart entry drafts atomically`.

## Task 6: Authenticated API

**Files**

- Create `backend/api/smart_entry.py`.
- Modify `backend/main.py`.
- Test `backend/tests/test_smart_entry_api.py`.

- [ ] Add:
  - `POST /api/v1/smart-entry-drafts`;
  - `GET /api/v1/smart-entry-drafts?date=YYYY-MM-DD`;
  - `GET|PATCH|DELETE /api/v1/smart-entry-drafts/{id}`;
  - `POST /api/v1/smart-entry-drafts/{id}/analyze`;
  - `POST /api/v1/smart-entry-drafts/{id}/confirm`.
- [ ] Require authentication on every route.
- [ ] Use `If-Match` for update/analyze/confirm and UUID `Idempotency-Key` for confirmation.
- [ ] Return `processing_mode='deterministic'` for parse/edit/confirm and `processing_mode='agent'` only for analyze.
- [ ] Localize stable errors while preserving codes.
- [ ] Deprecate authenticated writes through `/calendar/agent-entry`; it must not create CSV records for signed-in users.
- [ ] Test OpenAPI contracts, auth, validation, owner isolation, conflicts, and processing mode.
- [ ] Commit `feat: expose smart entry draft workflow`.

## Task 7: Smart Entry Task Page

**Files**

- Create frontend files from the file map.
- Test `frontend/src/pages/SmartEntry.test.tsx`, `frontend/src/hooks/useSmartEntryDraft.test.tsx`, and `frontend/src/services/smartEntryApi.test.ts`.

- [ ] Add `/today/smart-entry?date=YYYY-MM-DD` and a Today action.
- [ ] Start with a large multiline text input and deterministic Parse command.
- [ ] Show each candidate as a selectable unframed row with source, issues, assumptions, and candidate choices.
- [ ] Provide labeled multiline fields rather than one compressed row.
- [ ] Keep unknown numeric values empty.
- [ ] Enable Analyze only when unresolved candidates exist and only after explicit click.
- [ ] Preserve deterministic candidates and local edits when Agent analysis fails.
- [ ] Require explicit acceptance of every Agent-estimated food or exercise value.
- [ ] Confirm only selected complete candidates and navigate to the selected day after success.
- [ ] Persist confirmation replay state across refresh with account/date-scoped recovery keys.
- [ ] Add complete Chinese/English strings and responsive styles with no horizontal overflow at `390x844`.
- [ ] Commit `feat: build smart entry review task`.

## Task 8: Phase Verification

- [ ] Run deterministic domain, repository, Agent-boundary, API, and frontend focused tests.
- [ ] Run the complete backend suite.
- [ ] Run the complete frontend suite and `tsc -b`.
- [ ] Run the production frontend build.
- [ ] Rebuild Docker and verify backend/frontend health.
- [ ] Desktop acceptance: parse a mixed Chinese entry, resolve catalog values, analyze one unknown food, explicitly accept it, confirm, and verify Today.
- [ ] Mobile acceptance at `390x844` with no overflow or console errors.
- [ ] Reload during a lost confirmation response and verify one idempotent result.
- [ ] Verify form and catalog flows remain usable with no model configuration.
- [ ] Review minimum-data model context, output schema, no direct writes, transaction rollback, owner isolation, and error recovery.
- [ ] Update README, roadmap, and this plan with exact evidence.
- [ ] Commit `docs: verify smart entry agent drafts`.
- [ ] Push the clean branch and verify local/remote SHA equality.

## Completion Criteria

- Deterministic parsing and local catalog matching work with no model connection.
- Agent analysis is explicit, structured, minimum-context, and limited to unresolved fields.
- Agent cannot invent actual completed workout quantities.
- User edits and estimate acceptance are required before formal writes.
- Multi-record confirmation is transactional and idempotent.
- Draft, formal records, and recovery state are account-scoped.
- Today reflects confirmed smart-entry records and never draft values.
- Backend, frontend, type, build, Docker, desktop, and mobile checks have current evidence.
