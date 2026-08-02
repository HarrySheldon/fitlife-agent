# Today Records Product Program Roadmap

**Source specification:** `docs/superpowers/specs/2026-07-19-today-nutrition-training-records-design.md`  
**Status:** Phases 1-6 implemented; Phase 6 runtime acceptance evidence is tracked in its implementation plan.

**Excluded:** Account data export, recipe builder, barcode/image recognition, PostgreSQL, external runtime catalog APIs

## Why This Is A Program

The approved specification replaces the persistence model, profile and target model, meal aggregate, workout aggregate, Today read model, local catalogs, and smart-entry write boundary. Implementing all of that as one task would leave the application broken between commits and make failures difficult to isolate.

The work is therefore split into six ordered, independently verifiable plans. Each plan must keep Docker startup and the existing authenticated product usable.

## Delivery Order

| Phase | Deliverable | Depends On | Product Proof |
| --- | --- | --- | --- |
| 1 (complete) | SQLite foundation and migration runtime | None | App starts against a versioned local database without changing current API behavior |
| 2 (complete) | Versioned profile and deterministic daily targets | Phase 1 | New users confirm profile, overall goal, activity and four daily targets |
| 3 (complete) | Food catalog and meal drafts | Phases 1-2 | Users search foods, build a multi-item meal draft and atomically confirm it |
| 4 (complete) | Exercise catalog, workout sessions and Today summary | Phases 1-3 | Users record strength/cardio sessions and Today shows four nutrients plus optional training |
| 5 (complete) | Smart entry and Agent analysis drafts | Phases 2-4 | Deterministic parsing runs first and Agent only fills unresolved draft fields |
| 6 (complete) | Controlled catalog imports, legacy cutover and release hardening | Phases 1-5 | Imports and CSV migration are idempotent, licensed, verified and readiness-tested |

## Cross-Phase Invariants

- Fixed calculations work without a model connection.
- Agent output never writes confirmed records directly.
- Drafts never affect daily summaries.
- Every confirmed multi-record operation is transactional.
- Every row is scoped by `user_id`; authenticated users cannot read another user's data.
- Historical records store value snapshots and provenance.
- New account-owned database rows participate in account deletion.
- Existing account export is not expanded in this program and must not be presented as exporting the new SQLite record model.
- Public catalog updates never mutate historical records.

## Plan Files

The completed Phase 1 and Phase 2 plans are:

- `docs/superpowers/plans/2026-07-19-sqlite-records-foundation.md`
- `docs/superpowers/plans/2026-07-22-profile-daily-targets.md`

Plans 3-6 are written after the preceding phase lands so their exact paths and signatures match the code actually delivered. This prevents speculative plans from drifting from the repository while preserving the approved order and boundaries above.

## Phase 2 Verification Evidence

**Verified:** 2026-07-24

- Backend full suite: `550 passed`, one known Starlette/httpx warning, `168.12s`.
- Frontend full suite: `113 passed` across `18` files.
- Production frontend build: success with `2448` modules transformed; the existing chunk-size warning above `500 kB` remains.
- `docker compose config --quiet` passed.
- The first Docker build exposed a frontend `node_modules` junction conflict in the build context. Commit `457fa8e` added `frontend/.dockerignore`; the next `docker compose up --build -d` passed.
- Backend and frontend containers were up on ports `8000` and `3000`; the backend health endpoint returned `ok`.
- `docker compose restart` passed and backend health recovered.
- Desktop browser acceptance registered a fresh account, completed fat-loss onboarding, confirmed `2172 kcal`, `291 g` carbohydrates, `126 g` protein, and `56 g` fat, and verified the saved version in Profile history.
- Mobile browser acceptance at `390x844` registered another account, completed muscle-gain onboarding, confirmed `2811 kcal`, `451 g` carbohydrates, `126 g` protein, and `56 g` fat, and verified the saved values in Profile. Every onboarding step had no horizontal overflow and the console had no errors.
- The authenticated setup API returned `setup_complete: true` after confirmation.
- The legacy per-user CSV-backed dashboard summary still responded after confirmation; CSV meal and workout storage remains active.
- Final review regression coverage verifies deletion/write lifecycle exclusion, narrow training-personalization writes, stable effective-time conflicts, latest-target legacy projection, coded safety conditions, and accurately scoped legacy-record export messaging.

Account data export remains explicitly excluded from this program.

## Phase 4 Verification Evidence

**Verified:** 2026-08-02

- Backend full suite: 772 passed; frontend full suite: 157 passed across 28 files.
- TypeScript and Vite production build transformed 2466 modules successfully; the existing chunk-size warning remains.
- Main rebuilt on isolated Docker ports 19000/14000. Both services were healthy and readiness reported schema 3 with zero catalog or migration failures.
- Desktop acceptance confirmed one mixed 45-minute strength/cardio session with a visibly labeled 516 kcal estimate; reload retained exactly one session.
- Mobile acceptance at `390x844` had no horizontal overflow or console errors, including the corrected exercise search field.
- Final review covered authorization, FTS safety, immutable snapshots, estimate provenance, optimistic locking, transactional confirmation, idempotency, account deletion, and legacy compatibility.

## Phase 5 Verification Evidence

**Verified:** 2026-08-02

- Python 3.12.13 Docker evidence passed private-catalog isolation, inactive-item exclusion, and smart-entry resolution, 8/8.
- Browser acceptance parsed one mixed Chinese entry, resolved three local catalog candidates, explicitly analyzed and accepted one unknown-food estimate, and confirmed two meals plus one workout.
- Today reported 799 kcal, 116 g carbohydrate, 49 g protein, and 17 g fat after confirmation; reload retained the same formal-record counts.
- No-model acceptance preserved all four deterministic candidates and returned a recoverable configuration error only after the explicit Agent action.
- The lost-response hook and repository replay tests prove refresh recovery reuses one idempotency key and creates one formal aggregate.
- Desktop and `390x844` candidate editing had no horizontal overflow or console errors.
- Final review covered minimum model context, strict structured output, no Agent writes, stale-result defense, transaction rollback, owner isolation, and recoverable errors.

## Phase 6 Verification Evidence

**Verified:** 2026-07-31

- Backend full suite: `770 passed`, one known Starlette/httpx warning, `74.12s`.
- Frontend full suite: `157 passed` across `28` files, `33.84s`.
- TypeScript and production Vite build: success with `2466` modules transformed in `20.00s`; the existing chunk-size warning above `500 kB` remains.
- `docker compose config --quiet`: passed with configurable frontend/backend ports, persistent backend data, two health checks and frontend dependency on backend readiness.
- Focused migration evidence covers canonical catalog checksums, rollback, read-only source archives, reconciliation, sticky per-user cutover, transactional upload replay, account deletion, startup ordering and degraded readiness.
- Final Docker rebuild passed on isolated ports `18000` and `13000`; readiness reported schema `3` and zero catalog/migration failures. Both containers returned to `healthy` after an explicit full-stack restart.
- Desktop browser acceptance migrated a real legacy meal/workout account, confirmed catalog meal entry without a model, verified an explicit unresolved Agent request fails clearly without configuration, and replayed the same signed-in CSV upload. Desktop and `390x844` had no document overflow or console warnings/errors.
- `npm audit` reported zero vulnerabilities for both production-only and complete dependency trees.
- The live backup CLI created a `552960` byte SQLite image and reported SHA-256 `ff33137b3457c7dc1da34f48beae48b79977184ef7c858ecb3bf5968967d9c45` after `quick_check`.
- Runtime deletion of the migrated acceptance account removed its read-only archive and directory, invalidated login with `401`, and preserved the account deletion contract.

## Phase 3 Verification Evidence

**Verified:** 2026-07-25

- Backend full suite: `650 passed`, one known Starlette/httpx warning, `76.65s`.
- Frontend full suite: `123 passed` across `21` files. One initial run hit the existing `5s` Profile test timeout; the focused test and a fresh full run passed.
- Production frontend build: success with `2454` modules transformed in `49.59s`; the existing chunk-size warning above `500 kB` remains.
- `docker compose config --quiet`, rebuild, startup, backend health, and frontend Nginx response passed on ports `8000` and `3000`.
- Desktop browser acceptance confirmed a three-item meal containing two audited public foods and one complete private custom food. There was no horizontal overflow and no console warning or error.
- Mobile browser acceptance at `390x844` confirmed a second three-item meal containing two audited public foods and one complete private custom food. There was no horizontal overflow and no console warning or error.
- After reload, SQLite contained exactly two meals in positions `1` and `2`, each with three immutable item snapshots; no duplicate confirmation occurred.
- Final review covered authorization, FTS query safety, optimistic locking, idempotency, transaction rollback, historical snapshots, account deletion, and the excluded export boundary with no Critical or Important findings.
- Today continues to read the legacy record projection. Phase 4 owns the SQLite meal/workout summary cutover.
