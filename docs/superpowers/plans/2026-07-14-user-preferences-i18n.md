# User Preferences and i18n Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-user language, unit-system, and IANA-timezone preferences, then apply them consistently across the authenticated product without changing metric source data.

**Architecture:** A preferences application service owns validated per-user settings behind a repository port. FastAPI resolves account-local dates from those preferences; React uses i18next for interface text and a preferences context for immediate language/unit updates. Domain data remains metric and conversion occurs only at frontend input/display boundaries.

**Tech Stack:** FastAPI, Pydantic v2, Python `zoneinfo`, React 19, i18next, react-i18next, TypeScript, Vitest, Testing Library.

**Practice references:** Open WebUI i18next resource loading (`src/lib/i18n/index.ts`) and browser-timezone synchronization (`src/routes/+layout.svelte`, `src/lib/apis/auths/index.ts`); ECMAScript `Intl` for locale/timezone presentation.

---

### Task 1: Per-user preferences domain, persistence, and API

**Files:**
- Create: `backend/domain/user_preferences.py`
- Create: `backend/application/ports/user_preferences_repository.py`
- Create: `backend/application/use_cases/user_preferences.py`
- Create: `backend/infrastructure/settings/file_user_preferences_repository.py`
- Modify: `backend/api/settings.py`
- Modify: `backend/schemas.py`
- Test: `backend/tests/application/test_user_preferences.py`
- Test: `backend/tests/test_preferences_api.py`

- [x] Write failing tests for defaults, IANA timezone validation, per-user isolation, atomic persistence, GET/PATCH authentication, partial updates, and initialization from `X-Timezone`/`Accept-Language` only when no account preference exists.
- [x] Run the focused tests and confirm RED because preference types and endpoints do not exist.
- [x] Implement `UserPreferences(language, unit_system, timezone)`, repository and get/update use cases; reject unknown locales, unit systems, and timezones with stable validation errors.
- [x] Add `GET /settings/preferences` and `PATCH /settings/preferences`, returning only the current user's settings with `processing_mode=deterministic`.
- [x] Run focused tests and confirm GREEN.
- [x] Commit as `feat: add per-user general preferences`.

### Task 2: Account-local today and week boundaries

**Files:**
- Create: `backend/domain/account_clock.py`
- Modify: `backend/api/today.py`
- Modify: `backend/api/dashboard.py`
- Modify: `backend/api/report.py`
- Modify: `backend/application/use_cases/generate_weekly_report.py`
- Test: `backend/tests/domain/test_account_clock.py`
- Test: `backend/tests/test_timezone_boundaries.py`

- [x] Write failing tests around UTC day/week boundaries proving two users in different IANA timezones receive different implicit `today` and week windows while explicit date parameters remain unchanged.
- [x] Run focused tests and confirm RED.
- [x] Implement an injectable UTC clock plus `local_today()` and `local_week_bounds()` using `zoneinfo.ZoneInfo`.
- [x] Resolve the current user's timezone for implicit Today, Dashboard, and weekly report requests; do not rewrite historical record dates.
- [x] Run focused tests and confirm GREEN.
- [x] Commit as `feat: apply account timezone date boundaries`.

### Task 3: Frontend i18n and preferences runtime

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/src/i18n/index.ts`
- Create: `frontend/src/i18n/resources/en-US.ts`
- Create: `frontend/src/i18n/resources/zh-CN.ts`
- Create: `frontend/src/hooks/usePreferences.tsx`
- Create: `frontend/src/test/setup.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/vite.config.ts`
- Test: `frontend/src/hooks/usePreferences.test.tsx`

- [x] Add i18next/react-i18next and Vitest/Testing Library dependencies and a `test` script.
- [x] Write failing tests proving pre-login language comes from local storage, authenticated preferences override cache, browser timezone is supplied for first initialization, and updates immediately change `<html lang>` plus persisted account state.
- [x] Run the focused tests and confirm RED.
- [x] Configure typed translation resources and a `PreferencesProvider` that is independent from model settings and auth form state.
- [x] Add API methods/headers for preferences and expose `language`, `unitSystem`, `timezone`, `updatePreferences`, and `localDate()`.
- [x] Run focused tests and confirm GREEN.
- [x] Commit as `feat: add preferences and i18n runtime`.

### Task 4: General settings task page and metric/imperial conversion

**Files:**
- Create: `frontend/src/domain/units.ts`
- Create: `frontend/src/pages/settings/GeneralSettings.tsx`
- Modify: `frontend/src/pages/settings/SettingsHome.tsx`
- Modify: `frontend/src/routes/AppRoutes.tsx`
- Modify: `frontend/src/components/ProfileForm.tsx`
- Modify: `frontend/src/components/TargetProgress.tsx`
- Modify: `frontend/src/pages/Today.tsx`
- Modify: `frontend/src/pages/Logbook.tsx`
- Modify: `frontend/src/styles/index.css`
- Test: `frontend/src/domain/units.test.ts`
- Test: `frontend/src/pages/settings/GeneralSettings.test.tsx`

- [x] Write failing tests for kg/lb, cm/ft-in, and km/mi round trips; prove saving converted profile/workout inputs sends metric values and switching units does not mutate stored source records.
- [x] Run focused tests and confirm RED.
- [x] Implement pure conversion/format helpers with explicit rounding at display boundaries only.
- [x] Build `/settings/general` with immediate language selection, descriptive metric/imperial radio rows, and IANA timezone selection; keep request state isolated from `/settings/model`.
- [x] Apply unit-aware inputs and displays to profile, meal/workout records, target progress, Today, and Logbook.
- [x] Run focused tests and confirm GREEN.
- [x] Commit as `feat: add general settings and unit conversion`.

### Task 5: Translate the complete product shell

**Files:**
- Create: `backend/i18n.py`
- Modify: `backend/api/utils.py`
- Modify: `backend/api/auth.py`
- Modify: `backend/domain/errors.py`
- Modify: `backend/agent/graph.py`
- Modify: `frontend/src/pages/*.tsx`
- Modify: `frontend/src/pages/settings/*.tsx`
- Modify: `frontend/src/components/*.tsx`
- Modify: `frontend/src/hooks/*.tsx`
- Modify: `frontend/src/i18n/resources/en-US.ts`
- Modify: `frontend/src/i18n/resources/zh-CN.ts`
- Test: `frontend/src/App.i18n.test.tsx`
- Test: `backend/tests/test_localized_api_messages.py`
- Test: `backend/tests/application/test_agent_boundary.py`

- [x] Write route/API tests proving Chinese/English coverage for authentication, navigation, Today, Logbook, Review, Plan, Profile, Evaluation, settings, loading, empty, validation, and fixed API error states; Agent answer content remains untouched. Evidence: the frontend route/state suite passes 30 tests, including real registration validation and rendered Evaluation results in both locales; the 47-test backend focused run includes localized upload success/error coverage and Agent boundary assertions.
- [x] Run the route-level test and confirm RED on remaining literal UI strings. Evidence: the initial route run failed 11 of 24 cases and the tracked-string scan reported 215 literals; review regressions later produced 10 focused frontend failures and 2 localized-upload failures before the fixes.
- [x] Resolve authenticated backend messages from account language and unauthenticated messages from `Accept-Language`; keep stable error codes language-neutral and translate only public messages. Evidence: `backend/tests/test_localized_api_messages.py` passes 10 tests, including authenticated upload messages in both locales and stable `INVALID_UPLOAD_FILE` errors.
- [x] Add language, unit system, and timezone to Agent context metadata while leaving the user's question language as the answer-language signal. Evidence: `test_agent_adds_preferences_as_context_without_changing_question_or_answer` passes.
- [x] Replace product-facing literals with translation keys while preserving structured record content and Agent output. Evidence: the complete frontend suite passes 50 tests, including localized Evaluation summaries/labels and exact Agent Markdown preservation.
- [x] Add a tracked-string scan test that fails when untranslated literals are introduced in product components outside approved data values. Evidence: `frontend/src/i18n/trackedStrings.test.ts` passes 8 tests and explicitly detects the prior Evaluation helper strings, service fallback, and JSX expression literal patterns.
- [x] Run frontend tests and production build. Evidence: Vitest passes 8 files/50 tests; Vite transforms 2438 modules and completes the production build.
- [ ] Inspect desktop/mobile `/settings/general` and one core page in both languages. Blocked evidence: local services started successfully, but the in-app Browser reported no connectable browser backend, so no visual inspection is claimed.
- [x] Commit as `feat: localize the complete product interface`.
