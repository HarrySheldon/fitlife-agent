# Today Records Product Program Roadmap

**Source specification:** `docs/superpowers/specs/2026-07-19-today-nutrition-training-records-design.md`  
**Status:** Phases 1-2 complete; Phases 3-6 pending

**Excluded:** Account data export, recipe builder, barcode/image recognition, PostgreSQL, external runtime catalog APIs

## Why This Is A Program

The approved specification replaces the persistence model, profile and target model, meal aggregate, workout aggregate, Today read model, local catalogs, and smart-entry write boundary. Implementing all of that as one task would leave the application broken between commits and make failures difficult to isolate.

The work is therefore split into six ordered, independently verifiable plans. Each plan must keep Docker startup and the existing authenticated product usable.

## Delivery Order

| Phase | Deliverable | Depends On | Product Proof |
| --- | --- | --- | --- |
| 1 (complete) | SQLite foundation and migration runtime | None | App starts against a versioned local database without changing current API behavior |
| 2 (complete) | Versioned profile and deterministic daily targets | Phase 1 | New users confirm profile, overall goal, activity and four daily targets |
| 3 | Food catalog and meal drafts | Phases 1-2 | Users search foods, build a multi-item meal draft and atomically confirm it |
| 4 | Exercise catalog, workout sessions and Today summary | Phases 1-3 | Users record strength/cardio sessions and Today shows four nutrients plus optional training |
| 5 | Smart entry and Agent analysis drafts | Phases 2-4 | Deterministic parsing runs first and Agent only fills unresolved draft fields |
| 6 | Controlled catalog imports, legacy cutover and release hardening | Phases 1-5 | Imports and CSV migration are idempotent, licensed, verified and Docker-tested |

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

**Verified:** 2026-07-23

- Backend full suite: `537 passed`, one known Starlette/httpx warning, `47.51s`.
- Frontend full suite: `112 passed` across `18` files.
- Production frontend build: success with `2448` modules transformed; the existing chunk-size warning above `500 kB` remains.
- `docker compose config --quiet` passed.
- The first Docker build exposed a frontend `node_modules` junction conflict in the build context. Commit `457fa8e` added `frontend/.dockerignore`; the next `docker compose up --build -d` passed.
- Backend and frontend containers were up on ports `8000` and `3000`; the backend health endpoint returned `ok`.
- `docker compose restart` passed and backend health recovered.
- Desktop browser acceptance registered a fresh account, completed fat-loss onboarding, confirmed `2172 kcal`, `291 g` carbohydrates, `126 g` protein, and `56 g` fat, and verified the saved version in Profile history.
- Mobile browser acceptance at `390x844` registered another account, completed muscle-gain onboarding, confirmed `2811 kcal`, `451 g` carbohydrates, `126 g` protein, and `56 g` fat, and verified the saved values in Profile. Every onboarding step had no horizontal overflow and the console had no errors.
- The authenticated setup API returned `setup_complete: true` after confirmation.
- The legacy per-user CSV-backed dashboard summary still responded after confirmation; CSV meal and workout storage remains active.

Phase 3 and account data export were not implemented as part of this verification.
