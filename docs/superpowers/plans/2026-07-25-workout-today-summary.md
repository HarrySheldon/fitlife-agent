# Workout Sessions And Today Summary Implementation Plan

**Status:** Approved for autonomous execution
**Date:** 2026-07-25
**Goal:** Let authenticated users search a local exercise catalog, build and atomically confirm mixed strength/cardio workout sessions, and make Today read its nutrition and training state from SQLite.

## Architecture And Open-Source Practice

The source specification is
`docs/superpowers/specs/2026-07-19-today-nutrition-training-records-design.md`.
The implementation remains inside the modular monolith and follows patterns
reviewed in:

- [wger](https://github.com/wger-project/wger): separate exercise identity,
  primary/secondary muscles, workout sessions, and set-level logs. wger is
  AGPL-3.0, so this project uses the data-modeling lessons without copying code.
- [FitTrackee](https://github.com/SamR1/FitTrackee): keep activity duration,
  device values, calculated values, and record ownership explicit. FitTrackee
  is AGPL-3.0, so no implementation code is copied.
- [free-exercise-db](https://github.com/yuhonas/free-exercise-db): Unlicense
  public-domain exercise IDs and structured primary/secondary muscle metadata.

Phase 4 preserves these boundaries:

- Runtime exercise search is local-only.
- Public catalog data and user-owned custom exercises remain isolated.
- A workout session may contain strength exercises and cardio items together.
- Compact strength input expands into immutable set snapshots at confirmation.
- Device calories win when supplied; otherwise cardio uses the deterministic
  MET formula.
- Strength calories are shown only when duration and intensity are available,
  and are always labeled as estimates.
- Drafts do not affect Today.
- Confirmation is one SQLite transaction with optimistic locking and
  idempotency.
- Today reads confirmed SQLite meals and workouts for authenticated users.
- No Agent call exists in this phase.

## Task 1: Deterministic Exercise Domain

- [x] Add immutable strength/cardio values and stable domain errors.
- [x] Implement `MET * 3.5 * weight_kg / 200 * minutes` with decimal
  half-up rounding.
- [x] Prefer device calories over MET calculations.
- [x] Implement versioned low/medium/high strength MET estimates only when
  duration is present.
- [x] Test positive bounds, bodyweight sets, repeated compact sets, snapshots,
  estimate metadata, and missing-estimate behavior.
- [ ] Commit `feat: calculate deterministic workout estimates`.

## Task 2: Local Exercise Catalog

- [x] Add exercise catalog port, service, SQLite adapter, and seed loader.
- [x] Search names and aliases through the existing FTS table.
- [x] Enforce public/private visibility and active records in SQL.
- [x] Rank recent, favorite, private, then public entries.
- [x] Require a name, type, and primary muscle for custom exercises.
- [x] Seed a small audited Unlicense strength catalog and a small reviewed
  cardio/MET catalog with source, version, license, attribution, and aliases.
- [x] Test idempotency, provenance retention, deactivation, aliases, ownership,
  favorites, and account deletion.
- [ ] Commit `feat: add local searchable exercise catalog`.

## Task 3: Workout Drafts And Atomic Confirmation

- [ ] Add workout repository port, use case, and SQLite adapter.
- [ ] Support create/get/update/delete for 30-day workout drafts.
- [ ] Resolve catalog exercises into immutable snapshots at draft save time.
- [ ] Validate strength exercises, ordered sets, cardio duration, and custom
  exercise requirements.
- [ ] Reject stale versions and expired drafts.
- [ ] Confirm the session, strength exercises, strength sets, cardio items,
  usage rows, custom catalog rows, and idempotency result in one transaction.
- [ ] Test owner isolation, rollback, concurrent retries, catalog mutation
  stability, and mixed-session confirmation.
- [ ] Commit `feat: confirm workout drafts atomically`.

## Task 4: Authenticated Workout APIs

- [ ] Add focused request/response schemas and authenticated routes:
  - `GET /api/v1/catalog/exercises/search`
  - `POST /api/v1/catalog/exercises/custom`
  - `PUT|DELETE /api/v1/catalog/exercises/{id}/favorite`
  - `POST /api/v1/workout-drafts`
  - `GET|PATCH|DELETE /api/v1/workout-drafts/{id}`
  - `POST /api/v1/workout-drafts/{id}/confirm`
- [ ] Require `If-Match` for updates/confirmation and a UUID
  `Idempotency-Key` for confirmation.
- [ ] Reuse lifecycle guards and localized stable errors.
- [ ] Test authentication, validation, owner isolation, `404`, `409`, and
  `422` contracts.
- [ ] Commit `feat: expose workout draft workflow`.

## Task 5: SQLite Daily Summary

- [ ] Add a read-model port/service/SQLite adapter for one authenticated day.
- [ ] Return effective four-target snapshots, consumed calories/carbohydrates/
  protein/fat, planned and recorded meal counts, meal summaries, and optional
  workout summaries.
- [ ] Do not subtract training calories from nutrition progress.
- [ ] Hide empty meals and the training section when no session exists.
- [ ] Keep the unauthenticated demo path on legacy files.
- [ ] Replace authenticated `/today` reads with the SQLite read model.
- [ ] Test timezone-selected dates, target history, empty days, meal-only days,
  workout-only days, mixed days, owner isolation, and legacy compatibility.
- [ ] Commit `feat: aggregate authenticated days from sqlite`.

## Task 6: Workout Task Page And Today Product View

- [ ] Add focused workout types, API client, recoverable draft hook, and tests.
- [ ] Add `/today/workout/new?date=YYYY-MM-DD`.
- [ ] Build a catalog-first task page with session metadata, separate strength
  and cardio sections, compact set input, optional expanded per-set editing,
  deterministic estimate labels, draft save state, and explicit confirmation.
- [ ] Keep numeric fields empty until the user enters values.
- [ ] Support complete custom exercises when catalog search has no result.
- [ ] Replace Today's inline workout form with route navigation.
- [ ] Show four nutrition progress metrics, meal count vs planned meals,
  confirmed meal rows, and training only when present.
- [ ] Add complete English/Chinese strings and responsive styles.
- [ ] Run focused and complete frontend tests plus the production build.
- [ ] Commit `feat: build workout entry and sqlite today view`.

## Task 7: Integration And Acceptance

- [ ] Run the complete backend suite.
- [ ] Run the complete frontend suite and production build.
- [ ] Rebuild Docker and verify backend/frontend health.
- [ ] Desktop acceptance: search strength/cardio exercises, add a mixed
  session, confirm it, and verify Today shows four nutrition values plus
  training.
- [ ] Mobile acceptance at `390x844` with no horizontal overflow or console
  errors.
- [ ] Reload and verify no duplicate session.
- [ ] Review authorization, FTS safety, snapshots, estimate provenance,
  optimistic locking, idempotency, rollback, account deletion, and legacy
  compatibility.
- [ ] Update README, roadmap, and this plan with exact evidence.
- [ ] Commit `docs: verify workouts and sqlite today summary`.
- [ ] Push the clean branch and verify local/remote SHA equality.

## Completion Criteria

- Exercise search is local, source-aware, and ownership-safe.
- Custom strength/cardio exercises require complete identifying fields.
- Mixed workout drafts survive recoverable save failures.
- Confirmed sets and cardio items retain values and provenance snapshots.
- Cardio device values and deterministic estimates are visibly distinct.
- Strength estimates are optional, labeled, and never treated as precise.
- Today shows calories, carbohydrates, protein, and fat from confirmed SQLite
  meals and shows training only when confirmed sessions exist.
- No Agent or model connection is required.
- Backend, frontend, build, Docker, desktop, and mobile verification pass.
