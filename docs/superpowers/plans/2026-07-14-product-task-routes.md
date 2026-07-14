# Product Task Routes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Today, Logbook, Review, Plan, and Profile from multi-purpose demo pages into overview-first product surfaces with isolated task routes and confirmation boundaries.

**Architecture:** Overview routes fetch and display stable read models; create/edit/generate operations live in dedicated child routes with their own state. Smart entry returns a deterministic draft and writes nothing until explicit confirmation. Plans and weekly reports gain per-user persistence so list/detail routes represent real product state, while Coach opens in a contextual drawer with independent request state.

**Tech Stack:** FastAPI, Pydantic v2, repository ports, React Router, i18next, Vitest, Testing Library.

---

### Task 1: Confirmable smart-entry drafts and isolated record routes

**Files:**
- Modify: `backend/tools/calendar_store.py`
- Modify: `backend/api/calendar.py`
- Modify: `backend/schemas.py`
- Create: `frontend/src/pages/records/MealEntry.tsx`
- Create: `frontend/src/pages/records/WorkoutEntry.tsx`
- Create: `frontend/src/pages/records/SmartEntry.tsx`
- Modify: `frontend/src/pages/Today.tsx`
- Modify: `frontend/src/routes/AppRoutes.tsx`
- Modify: `frontend/src/services/api.ts`
- Test: `backend/tests/test_smart_entry_confirmation.py`
- Test: `frontend/src/pages/records/RecordEntry.test.tsx`

- [ ] Write failing tests proving smart parsing returns meal/workout drafts without writing CSV, invalid drafts retain source text, and only explicit record POST calls persist confirmed drafts.
- [ ] Run focused tests and confirm RED.
- [ ] Replace direct-write `/calendar/agent-entry` behavior with a draft endpoint and typed proposed records; retain a compatibility response only if it also performs no write.
- [ ] Make `/today` read-only and add `/today/meal/new`, `/today/workout/new`, and `/today/smart-entry` pages with back paths and isolated request state.
- [ ] Run focused backend/frontend tests and confirm GREEN.
- [ ] Commit as `feat: split confirmable record entry tasks`.

### Task 2: Logbook date navigation and detail route

**Files:**
- Create: `frontend/src/pages/logbook/LogbookDay.tsx`
- Modify: `frontend/src/pages/Logbook.tsx`
- Modify: `frontend/src/routes/AppRoutes.tsx`
- Test: `frontend/src/pages/logbook/LogbookRoutes.test.tsx`

- [ ] Write failing tests proving `/logbook` only owns date browsing and `/logbook/:date` owns record detail/actions without embedding create forms or CSV upload in the overview.
- [ ] Run focused tests and confirm RED.
- [ ] Convert calendar tiles to stable date links, move detail into `LogbookDay`, and provide contextual links to the dedicated record routes.
- [ ] Keep CSV import as an optional input task on a dedicated `/logbook/import` route rather than the overview.
- [ ] Run focused tests and confirm GREEN.
- [ ] Commit as `feat: split logbook date and import tasks`.

### Task 3: Persisted weekly reports and review routes

**Files:**
- Create: `backend/application/ports/report_repository.py`
- Create: `backend/infrastructure/repositories/file_report_repository.py`
- Create: `backend/application/use_cases/reports.py`
- Modify: `backend/api/report.py`
- Create: `frontend/src/pages/review/WeeklyReview.tsx`
- Modify: `frontend/src/pages/Review.tsx`
- Modify: `frontend/src/routes/AppRoutes.tsx`
- Modify: `frontend/src/services/api.ts`
- Test: `backend/tests/application/test_reports.py`
- Test: `frontend/src/pages/review/ReviewRoutes.test.tsx`

- [ ] Write failing tests for per-user report save/list/get, week-key validation, explicit generation, and user isolation.
- [ ] Run focused tests and confirm RED.
- [ ] Persist deterministic weekly reports under the authenticated user directory and expose list/detail/generate endpoints keyed by ISO week.
- [ ] Keep `/review` trend-only; use `/review/week/:week` for report detail and explicit Agent interpretation.
- [ ] Run focused tests and confirm GREEN.
- [ ] Commit as `feat: add persisted weekly review routes`.

### Task 4: Confirmed plan drafts, persistence, and plan routes

**Files:**
- Create: `backend/application/ports/plan_repository.py`
- Create: `backend/infrastructure/repositories/file_plan_repository.py`
- Create: `backend/application/use_cases/plans.py`
- Modify: `backend/api/plan.py`
- Modify: `backend/schemas.py`
- Create: `frontend/src/pages/plan/NewPlan.tsx`
- Create: `frontend/src/pages/plan/PlanDetail.tsx`
- Modify: `frontend/src/pages/Plan.tsx`
- Modify: `frontend/src/routes/AppRoutes.tsx`
- Modify: `frontend/src/services/api.ts`
- Test: `backend/tests/application/test_plans.py`
- Test: `frontend/src/pages/plan/PlanRoutes.test.tsx`

- [ ] Write failing tests proving generation returns a validated draft, invalid drafts cannot activate, confirmation creates a per-user plan ID, and list/detail never cross users.
- [ ] Run focused tests and confirm RED.
- [ ] Implement deterministic and Agent-adjusted drafts separately from activation/persistence; validate both draft kinds and expose list/detail/draft/activate endpoints.
- [ ] Keep `/plan` as current-plan/list overview, `/plan/new` as generation plus confirmation, and `/plan/:planId` as detail with Agent adjustment draft plus explicit confirmation.
- [ ] Run focused tests and confirm GREEN.
- [ ] Commit as `feat: add confirmed plan task routes`.

### Task 5: Profile summary/edit route and contextual Coach drawer

**Files:**
- Create: `frontend/src/pages/profile/EditProfile.tsx`
- Create: `frontend/src/components/CoachDrawer.tsx`
- Modify: `frontend/src/pages/Profile.tsx`
- Modify: `frontend/src/components/CoachPanel.tsx`
- Modify: `frontend/src/pages/Today.tsx`
- Modify: `frontend/src/pages/review/WeeklyReview.tsx`
- Modify: `frontend/src/pages/plan/PlanDetail.tsx`
- Modify: `frontend/src/routes/AppRoutes.tsx`
- Modify: `frontend/src/styles/index.css`
- Test: `frontend/src/pages/profile/ProfileRoutes.test.tsx`
- Test: `frontend/src/components/CoachDrawer.test.tsx`

- [ ] Write failing tests proving `/profile` is read-only, `/profile/edit` owns profile form state, closing/reopening Coach does not mutate page form state, and each drawer request carries its route context.
- [ ] Run focused tests and confirm RED.
- [ ] Move `ProfileForm` to the edit route and render a unit-aware summary plus edit action on `/profile`.
- [ ] Wrap Coach in an accessible drawer with independent loading/error/result state and responsive close/focus behavior.
- [ ] Run focused tests and confirm GREEN.
- [ ] Commit as `feat: split profile and contextual coach tasks`.

### Task 6: Complete route matrix and delivery verification

**Files:**
- Modify: `frontend/src/pages/settings/SettingsHome.tsx`
- Modify: `frontend/src/routes/AppRoutes.tsx`
- Modify: `frontend/src/styles/index.css`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-07-12-user-settings-and-execution-boundaries-design.md`
- Modify: `docs/superpowers/plans/2026-07-14-*.md`

- [ ] Add a route-matrix regression test covering every settings and product task route, auth protection, back navigation, and mobile text/layout constraints.
- [ ] Run all backend and frontend tests plus the frontend production build.
- [ ] Start backend/frontend and exercise registration, preferences, model settings, password rotation, session revocation, export, record confirmation, report/plan persistence, and account deletion through API smoke tests.
- [ ] Inspect settings, Today, record entry, Logbook day, Review week, Plan detail, Profile edit, security, and privacy at desktop/mobile widths in both languages; confirm no horizontal overflow or console errors.
- [ ] Update documentation and every plan checkbox using observed evidence only.
- [ ] Commit as `docs: verify complete settings and task routes`.
