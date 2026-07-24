# Versioned Profile And Daily Targets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Complete and verified on 2026-07-24

**Goal:** Let authenticated users version their body profile and overall goal, calculate or manually confirm four daily nutrition targets, and complete a required onboarding flow without replacing the still-active CSV meal and workout repositories.

**Architecture:** Add a deterministic domain calculator, SQLite repository port/adapter, and application service behind authenticated `/api/v1` routes. SQLite is authoritative for the new versioned profile/goal/target model; a narrow compatibility projection updates the legacy JSON profile only after target confirmation so existing Today, Dashboard, report, and plan behavior remains usable until the later cutover phase. The frontend consumes one aggregate setup resource, keeps profile/goal/target steps separate, and redirects authenticated users to onboarding until all required versions exist.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, sqlite3, pytest, React 19, TypeScript, React Router, Vitest, Testing Library, i18next

---

## Scope And Fixed Decisions

- Overall goals are only `fat_loss`, `maintenance`, or `muscle_gain`; Agent cannot write them.
- Deterministic daily targets use Mifflin-St Jeor, activity factors `1.2`, `1.375`, `1.55`, and `1.725`, goal adjustments `-15%`, `0%`, and `+10%`, protein `1.8 g/kg` for fat loss/muscle gain or `1.6 g/kg` for maintenance, fat `0.8 g/kg`, and remaining calories as carbohydrate.
- `neutral` energy estimation uses the midpoint constant `-78` between the male `+5` and female `-161` constants. Energy parameter is calculation input, not identity language.
- Use decimal half-up rounding: calories to whole kcal and macros to whole grams. Store formula version `mifflin_st_jeor_v1` and a structured rationale.
- The authenticated versioned workflow is an `18+` product boundary because the pinned SQLite schema only persists adult profiles. The domain calculator still rejects users under 18 defensively. Automatic calculation is also disabled when `auto_target_disabled` is true. Safety conditions are stored as codes; the product gives a restriction/medical-care message, not a substitute target.
- Manual hard ranges are calories `800-6000`, carbs `0-1000`, protein `20-400`, and fat `10-300`. Deviations over 20% from the deterministic baseline require explicit confirmation. Macro energy mismatch over 10% is a warning that also requires explicit confirmation.
- Updating profile or overall goal creates that version and returns a target recalculation preview. It never writes a daily target version until `/targets/confirm` succeeds. Preview freshness and request retry safety are separate: `If-Match` carries the current preview token, while `Idempotency-Key` carries a client-generated UUID.
- Agent target drafts remain out of scope for this phase. The existing Coach action may remain visible but cannot persist targets.
- Anonymous `/profile` and current file-backed meal/workout behavior remain unchanged.
- Account deletion erases the user's versioned SQLite data as well as their file-backed data and identity.
- Account export remains excluded.

## File Structure

| File | Responsibility |
| --- | --- |
| `backend/domain/profile_targets.py` | Domain values, deterministic formula, hard validation and warning calculation |
| `backend/application/ports/profile_target_repository.py` | Versioned profile/goal/target persistence contract |
| `backend/infrastructure/repositories/sqlite_profile_target_repository.py` | Transactional SQLite implementation |
| `backend/application/use_cases/profile_targets.py` | Authenticated orchestration, previews, confirmation and legacy projection |
| `backend/api/profile_targets.py` | `/api/v1` request/response boundary |
| `backend/schemas.py` | API-only Pydantic payloads for the new boundary |
| `backend/main.py` | Register the new router |
| `frontend/src/types/index.ts` | Setup aggregate, preview and confirmation types |
| `frontend/src/services/api.ts` | `/api/v1` client methods |
| `frontend/src/hooks/useProfileSetup.ts` | Setup query/mutation state |
| `frontend/src/pages/Onboarding.tsx` | Required first-run profile/goal/target flow |
| `frontend/src/pages/Profile.tsx` | Editable post-onboarding profile and target sections |
| `frontend/src/routes/AppRoutes.tsx` | Onboarding gate and route |

### Task 1: Deterministic Target Domain

**Files:**
- Create: `backend/domain/profile_targets.py`
- Create: `backend/tests/domain/test_profile_targets.py`
- Modify: `backend/tools/target_suggestions.py`
- Modify: `backend/tests/test_profile_personalization.py`

- [x] **Step 1: Write failing formula and safety tests**

Cover all energy parameters, activity levels and goals with a table-driven test. Assert exact half-up results, formula version, four macros, minimum energy floors, hard bounds, and automatic-calculation restrictions. Include tests that a manual target returns `requires_confirmation=True` for either the 20% baseline deviation or 10% macro-energy mismatch.

```python
def test_calculate_daily_targets_uses_approved_formula():
    profile = ProfileInput(
        age=30,
        height_cm=175,
        weight_kg=70,
        energy_parameter="male",
        activity_level="moderate",
        auto_target_disabled=False,
        safety_conditions=(),
    )
    result = calculate_daily_targets(profile, "fat_loss")

    assert result.formula_version == "mifflin_st_jeor_v1"
    assert result.calories == 2172
    assert result.protein == 126
    assert result.fat == 56
    assert result.carbs == 291
```

- [x] **Step 2: Run tests and verify RED**

```powershell
..\..\.venv\Scripts\python.exe -m pytest backend/tests/domain/test_profile_targets.py backend/tests/test_profile_personalization.py -q -p no:cacheprovider --basetemp .tmp\phase2-domain-red
```

Expected: collection fails because `backend.domain.profile_targets` does not exist.

- [x] **Step 3: Implement immutable domain values and calculator**

Use frozen dataclasses and `Decimal(...).quantize(Decimal("1"), ROUND_HALF_UP)`. Expose:

```python
def calculate_daily_targets(profile: ProfileInput, goal: OverallGoal) -> DailyTargets: ...
def evaluate_manual_targets(
    manual: DailyTargets,
    baseline: DailyTargets,
) -> TargetValidation: ...
```

Return stable error codes `TARGET_CALCULATION_RESTRICTED` and `TARGET_OUT_OF_RANGE`; warnings are `TARGET_BASELINE_DEVIATION` and `TARGET_MACRO_ENERGY_MISMATCH`.

Adapt `suggest_targets()` to call the new calculator and project calories/protein into its existing response so legacy callers keep their contract.

- [x] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all focused tests pass.

- [x] **Step 5: Commit**

```powershell
git add backend/domain/profile_targets.py backend/tests/domain/test_profile_targets.py backend/tools/target_suggestions.py backend/tests/test_profile_personalization.py
git commit -m "feat: calculate deterministic daily targets"
```

### Task 2: Versioned Profile Target Repository

**Files:**
- Create: `backend/application/ports/profile_target_repository.py`
- Create: `backend/infrastructure/repositories/sqlite_profile_target_repository.py`
- Create: `backend/tests/infrastructure/test_sqlite_profile_target_repository.py`
- Modify: `backend/infrastructure/repositories/__init__.py`
- Modify: `backend/application/use_cases/delete_account.py`
- Modify: `backend/api/account.py`
- Modify: `backend/tests/test_account_delete_api.py`

- [x] **Step 1: Write failing repository contract tests**

Test latest reads by `effective_from`, append-only profile/goal/target writes, user isolation, full target history order, atomic profile+goal bootstrap, and rollback on any invalid insert. Verify a target can only reference profile/goal versions owned by the same user. Test atomic `confirm_target_once` under sequential and concurrent retries, and verify account deletion erases only the selected user's SQLite rows.

```python
def test_repository_appends_versions_and_reads_latest(database):
    repository = SQLiteProfileTargetRepository(database)
    first = repository.append_profile("user-a", profile_at("2026-07-01"))
    latest = repository.append_profile("user-a", profile_at("2026-07-02", weight_kg=69))

    assert repository.get_latest_profile("user-a") == latest
    assert first.id != latest.id
```

- [x] **Step 2: Run tests and verify RED**

```powershell
..\..\.venv\Scripts\python.exe -m pytest backend/tests/infrastructure/test_sqlite_profile_target_repository.py -q -p no:cacheprovider --basetemp .tmp\phase2-repository-red
```

- [x] **Step 3: Implement the port and SQLite adapter**

The port exposes `get_setup`, `get_latest_profile`, `get_latest_goal`, `get_latest_target`, `append_profile`, `append_goal`, `append_target`, `confirm_target_once`, `list_targets`, `bootstrap`, and `delete_user_data`. `confirm_target_once` accepts a distinct client idempotency key and canonical request fingerprint, then writes the target and complete response into the existing `idempotency_keys` table in one transaction; a uniqueness race returns the stored response only when the fingerprint matches, otherwise it raises `IDEMPOTENCY_KEY_REUSED`. Generate UUIDs in the adapter, use ISO-8601 UTC timestamps supplied by an injected clock, parameterized SQL only, and one `SQLiteDatabase.transaction()` per command. Do not expose sqlite rows above the adapter. Use the tables already created by migration 1; do not modify either pinned migration.

Inject SQLite user-data deletion into `DeleteAccount` so the existing account workflow removes versioned profile, goal, target, idempotency, and any other user-owned SQLite rows in foreign-key-safe order. Extend account deletion tests with successful erasure, cross-user isolation, and cleanup failure behavior.

- [x] **Step 4: Run repository plus schema tests**

```powershell
..\..\.venv\Scripts\python.exe -m pytest backend/tests/infrastructure/test_sqlite_profile_target_repository.py backend/tests/infrastructure/test_records_schema.py -q -p no:cacheprovider --basetemp .tmp\phase2-repository-green
```

- [x] **Step 5: Commit**

```powershell
git add backend/application/ports/profile_target_repository.py backend/infrastructure/repositories/sqlite_profile_target_repository.py backend/infrastructure/repositories/__init__.py backend/tests/infrastructure/test_sqlite_profile_target_repository.py backend/application/use_cases/delete_account.py backend/api/account.py backend/tests/test_account_delete_api.py
git commit -m "feat: persist versioned profile targets"
```

### Task 3: Profile And Target Application Service

**Files:**
- Create: `backend/application/use_cases/profile_targets.py`
- Create: `backend/tests/application/test_profile_targets.py`
- Modify: `backend/application/use_cases/__init__.py`
- Modify: `backend/schemas.py`
- Modify: `backend/tests/test_profile_personalization.py`

- [x] **Step 1: Write failing orchestration tests**

Test incomplete and complete setup aggregates, profile/goal updates returning preview without target writes, deterministic confirmation, manual warning acknowledgement, stale preview rejection, target history and CSV compatibility projection only after confirmation.

```python
def test_profile_update_returns_preview_without_confirming_target(service, repository):
    result = service.update_profile("user-a", valid_profile_input())

    assert result.recalculation_preview is not None
    assert repository.get_latest_target("user-a") is None
```

- [x] **Step 2: Run tests and verify RED**

```powershell
..\..\.venv\Scripts\python.exe -m pytest backend/tests/application/test_profile_targets.py -q -p no:cacheprovider --basetemp .tmp\phase2-service-red
```

- [x] **Step 3: Implement use cases and optimistic preview token**

Create a preview token from canonical JSON containing profile version ID, goal version ID, target values, source, and formula version using SHA-256. `/targets/confirm` compares the `If-Match` header with the freshly recomputed token and rejects stale confirmation with HTTP 412 and `TARGET_PREVIEW_STALE`. Require `acknowledge_warnings=True` when validation requires confirmation. A separate required `Idempotency-Key` UUID makes confirmation retries idempotent; the same key and same canonical request returns the already-created response, while the same key with another request returns `IDEMPOTENCY_KEY_REUSED`.

Inject a `LegacyProfileProjection` protocol. Its file-backed implementation reads the existing `UserProfile`, updates only compatible height/weight/age/goal/calories/protein fields, and writes it after the SQLite target transaction succeeds. Align the legacy `UserProfile` upper bounds and calorie/protein target bounds with the pinned SQLite schema so valid confirmed values never fail projection; retain the legacy minimum age of 16 while the new API enforces 18+. A projection failure returns `TARGET_COMPATIBILITY_WRITE_FAILED` and must be observable; it must not pretend that SQLite confirmation failed.

- [x] **Step 4: Run service tests and verify GREEN**

Run the Step 2 command. Expected: all tests pass.

- [x] **Step 5: Commit**

```powershell
git add backend/application/use_cases/profile_targets.py backend/application/use_cases/__init__.py backend/tests/application/test_profile_targets.py backend/schemas.py backend/tests/test_profile_personalization.py
git commit -m "feat: orchestrate profile target versions"
```

### Task 4: Authenticated `/api/v1` Boundary

**Files:**
- Create: `backend/api/profile_targets.py`
- Create: `backend/tests/test_profile_targets_api.py`
- Modify: `backend/schemas.py`
- Modify: `backend/main.py`

- [x] **Step 1: Write failing API contract tests**

Create isolated registered users and cover authentication, user isolation, validation envelopes and these routes:

```text
GET  /api/v1/profile
PUT  /api/v1/profile
GET  /api/v1/goals
PUT  /api/v1/goals/overall
POST /api/v1/targets/calculate
POST /api/v1/targets/confirm
GET  /api/v1/targets/history
```

Assert profile/goal updates return `recalculation_preview`, calculate is deterministic, confirmation creates one version, stale `If-Match` returns 412, missing/invalid idempotency headers are rejected, same-key retries return the first result, changed-payload key reuse conflicts, unsafe/manual-warning requests return stable codes, and `/api/v1/targets/agent-draft` is absent in this phase.

- [x] **Step 2: Run tests and verify RED**

```powershell
..\..\.venv\Scripts\python.exe -m pytest backend/tests/test_profile_targets_api.py -q -p no:cacheprovider --basetemp .tmp\phase2-api-red
```

- [x] **Step 3: Implement API schemas, dependency factory and router**

Use `require_current_user`; API handlers parse/serialize only and call the service. Add `model_config = ConfigDict(extra="forbid")` to every new request model. Keep existing `/profile` untouched for anonymous demo compatibility.

- [x] **Step 4: Run API and legacy regressions**

```powershell
..\..\.venv\Scripts\python.exe -m pytest backend/tests/test_profile_targets_api.py backend/tests/test_optional_auth_api.py backend/tests/test_today_api.py backend/tests/test_api_basic.py -q -p no:cacheprovider --basetemp .tmp\phase2-api-green
```

- [x] **Step 5: Commit**

```powershell
git add backend/api/profile_targets.py backend/schemas.py backend/main.py backend/tests/test_profile_targets_api.py
git commit -m "feat: expose profile target workflow"
```

### Task 5: Frontend Setup Client And State

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/Dockerfile`
- Modify: `docker-compose.yml`
- Create: `frontend/src/services/api.profileTargets.test.ts`
- Create: `frontend/src/hooks/useProfileSetup.ts`
- Create: `frontend/src/hooks/useProfileSetup.test.tsx`

- [x] **Step 1: Write failing client and hook tests**

Test exact `/api/v1` paths, bearer behavior through the shared request helper, initial aggregate loading, preview replacement after profile/goal update, explicit confirmation, stale-preview errors and refetch after confirmation.

- [x] **Step 2: Run tests and verify RED**

```powershell
npm --prefix frontend test -- --run src/services/api.profileTargets.test.ts src/hooks/useProfileSetup.test.tsx
```

- [x] **Step 3: Add focused types, API methods and hook**

Keep `ProfileVersion`, `OverallGoalVersion`, `DailyTargetVersion`, `TargetPreview`, `TargetWarning`, and `ProfileSetup` separate. Do not extend the legacy `UserProfile` type with the new aggregate. Add a dedicated `VITE_API_V1_BASE_URL`: it defaults to `/api/v1` in development and is `http://localhost:8000/api/v1` in Docker. Configure Vite to proxy `/api/v1` without stripping that prefix while retaining the existing rewritten `/api` proxy for legacy routes. Client tests assert the final fetch URL in both base configurations.

- [x] **Step 4: Run focused frontend tests and verify GREEN**

Run the Step 2 command. Expected: all tests pass.

- [x] **Step 5: Commit**

```powershell
git add frontend/src/types/index.ts frontend/src/services/api.ts frontend/src/services/api.profileTargets.test.ts frontend/src/hooks/useProfileSetup.ts frontend/src/hooks/useProfileSetup.test.tsx frontend/vite.config.ts frontend/Dockerfile docker-compose.yml
git commit -m "feat: add profile setup client"
```

### Task 6: Required Onboarding Flow

**Files:**
- Create: `frontend/src/pages/Onboarding.tsx`
- Create: `frontend/src/pages/Onboarding.test.tsx`
- Create: `frontend/src/components/OnboardingGate.tsx`
- Create: `frontend/src/components/OnboardingGate.test.tsx`
- Modify: `frontend/src/routes/AppRoutes.tsx`
- Modify: `frontend/src/pages/Auth.tsx`
- Modify: `frontend/src/i18n/resources/en-US.ts`
- Modify: `frontend/src/i18n/resources/zh-CN.ts`
- Modify: `frontend/src/styles/index.css`

- [x] **Step 1: Write failing onboarding interaction tests**

Cover profile, overall goal/activity, deterministic preview, optional manual four-target editing, warning acknowledgement, final confirmation and redirect to `/`. Verify login respects its original destination when setup is already complete; registration and incomplete login land on `/onboarding`.

- [x] **Step 2: Run tests and verify RED**

```powershell
npm --prefix frontend test -- --run src/pages/Onboarding.test.tsx src/components/OnboardingGate.test.tsx
```

- [x] **Step 3: Implement one full-page multi-step workflow**

Use a progress indicator and one task per section, not cards nested in cards. Inputs are labeled, numeric values start from loaded values, goal uses a segmented control, activity uses a select, and all four target values remain visible together at confirmation. Safety restriction replaces the target form with the restriction message. State that calculated targets are estimates rather than medical advice. Warning acknowledgement starts unchecked and is cleared whenever the preview or manual values change. Do not expose Agent draft controls.

- [x] **Step 4: Run interaction tests and production build**

```powershell
npm --prefix frontend test -- --run src/pages/Onboarding.test.tsx src/components/OnboardingGate.test.tsx
npm --prefix frontend run build
```

- [x] **Step 5: Commit**

```powershell
git add frontend/src/pages/Onboarding.tsx frontend/src/pages/Onboarding.test.tsx frontend/src/components/OnboardingGate.tsx frontend/src/components/OnboardingGate.test.tsx frontend/src/routes/AppRoutes.tsx frontend/src/pages/Auth.tsx frontend/src/i18n/resources/en-US.ts frontend/src/i18n/resources/zh-CN.ts frontend/src/styles/index.css
git commit -m "feat: require profile target onboarding"
```

### Task 7: Decoupled Profile And Target Editing

**Files:**
- Modify: `frontend/src/pages/Profile.tsx`
- Create: `frontend/src/pages/Profile.test.tsx`
- Create: `frontend/src/components/ProfileDetailsForm.tsx`
- Create: `frontend/src/components/OverallGoalForm.tsx`
- Create: `frontend/src/components/DailyTargetsForm.tsx`
- Delete: `frontend/src/components/ProfileForm.tsx`
- Modify: `frontend/src/components/ProfileForm.units.test.tsx`
- Modify: `frontend/src/i18n/resources/en-US.ts`
- Modify: `frontend/src/i18n/resources/zh-CN.ts`
- Modify: `frontend/src/styles/index.css`

- [x] **Step 1: Write failing decoupled editing tests**

Verify the profile page has separate profile, overall-goal and daily-target sections; profile/goal save displays a preview but does not silently confirm it; target history is inspectable; manual warnings require an explicit checkbox; unit conversion remains correct.

- [x] **Step 2: Run tests and verify RED**

```powershell
npm --prefix frontend test -- --run src/pages/Profile.test.tsx src/components/ProfileForm.units.test.tsx
```

- [x] **Step 3: Split the existing form by responsibility**

Use the shared setup hook. Keep experience level and training preference in a small legacy personalization section until their versioned model is introduced; do not mix them into the target transaction. Replace the current Agent panel target persistence implication with explanatory advice only.

- [x] **Step 4: Run frontend regressions and build**

```powershell
npm --prefix frontend test -- --run
npm --prefix frontend run build
```

- [x] **Step 5: Commit**

```powershell
git add frontend/src/pages/Profile.tsx frontend/src/pages/Profile.test.tsx frontend/src/components/ProfileDetailsForm.tsx frontend/src/components/OverallGoalForm.tsx frontend/src/components/DailyTargetsForm.tsx frontend/src/components/ProfileForm.units.test.tsx frontend/src/i18n/resources/en-US.ts frontend/src/i18n/resources/zh-CN.ts frontend/src/styles/index.css
git rm frontend/src/components/ProfileForm.tsx
git commit -m "feat: separate profile and target editing"
```

### Task 8: Verify Phase 2 And Advance The Roadmap

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-07-19-today-records-program-roadmap.md`
- Modify: `docs/superpowers/plans/2026-07-22-profile-daily-targets.md`

- [x] **Step 1: Document the versioned target workflow**

State that authenticated profile/goal/target writes use SQLite, target calculation is deterministic and confirmation-based, and legacy CSV meal/workout storage remains active.

- [x] **Step 2: Run complete backend and frontend verification**

```powershell
..\..\.venv\Scripts\python.exe -m pytest backend/tests -q -p no:cacheprovider --basetemp .tmp\phase2-backend-full
npm --prefix frontend test -- --run
npm --prefix frontend run build
```

- [x] **Step 3: Validate Docker upgrade and onboarding**

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/health
```

Use browser automation at desktop and mobile widths to register a new user, complete onboarding, confirm four targets, reopen Profile, and verify the saved versions. Confirm existing CSV dashboard responses still work after target confirmation.

- [x] **Step 4: Mark Phase 2 complete only after evidence passes**

Update the roadmap row to `2 (complete)` and record exact test/build/Docker/browser evidence in this plan.

#### Verification Evidence (2026-07-24)

- Backend full suite: `550 passed`, one known Starlette/httpx warning, `168.12s`.
- Frontend full suite: `113 passed` across `18` files.
- Production frontend build: success with `2448` modules transformed. The existing chunk-size warning above `500 kB` remains.
- `docker compose config --quiet` passed.
- The first Docker build exposed a frontend `node_modules` junction conflict in the build context. Commit `457fa8e` added `frontend/.dockerignore`; the subsequent `docker compose up --build -d` passed.
- Backend and frontend containers were up on ports `8000` and `3000`. The backend health endpoint returned `ok`.
- `docker compose restart` passed and backend health recovered.
- Desktop acceptance registered a fresh account, completed fat-loss onboarding, confirmed `2172 kcal`, `291 g` carbohydrates, `126 g` protein, and `56 g` fat, and verified the saved target version in Profile history.
- Mobile acceptance at `390x844` registered another fresh account, completed muscle-gain onboarding, confirmed `2811 kcal`, `451 g` carbohydrates, `126 g` protein, and `56 g` fat, and verified the saved values in Profile. Every onboarding step had no horizontal overflow and the browser console had no errors.
- The authenticated setup API returned `setup_complete: true` after confirmation.
- The legacy per-user CSV-backed dashboard summary still responded after confirmation. Meal and workout CSV storage remains active in Phase 2.
- Final review regression coverage verifies deletion/write lifecycle exclusion, narrow training-personalization writes, stable effective-time conflicts, latest-target legacy projection, coded safety conditions, and accurately scoped legacy-record export messaging.

The evidence covers the Phase 2 implementation and acceptance boundary only. Phase 3 and the excluded account data export were not implemented.

- [x] **Step 5: Commit**

```powershell
git add README.md docs/superpowers/plans/2026-07-19-today-records-program-roadmap.md docs/superpowers/plans/2026-07-22-profile-daily-targets.md
git commit -m "docs: verify versioned profile targets"
```

## Completion Criteria

- Authenticated users have isolated append-only profile, overall-goal and target versions.
- Deterministic calculations match the approved formula and safety limits.
- Profile/goal changes only preview recalculation; confirmation is always explicit.
- Manual warnings require explicit acknowledgement.
- New and incomplete users cannot bypass onboarding into the product shell.
- Existing anonymous demo and CSV meal/workout workflows remain operational.
- Account deletion removes all of the user's file-backed and SQLite data without touching another user.
- Agent does not write overall goals or confirmed targets.
- Backend/frontend tests, build, Docker startup and browser acceptance pass.
- Phase 2 branch is clean and pushed before Phase 3 begins.
