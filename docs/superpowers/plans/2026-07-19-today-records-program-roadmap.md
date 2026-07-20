# Today Records Product Program Roadmap

**Source specification:** `docs/superpowers/specs/2026-07-19-today-nutrition-training-records-design.md`  
**Status:** Phase 1 complete; Phases 2-6 pending

**Excluded:** Account data export, recipe builder, barcode/image recognition, PostgreSQL, external runtime catalog APIs

## Why This Is A Program

The approved specification replaces the persistence model, profile and target model, meal aggregate, workout aggregate, Today read model, local catalogs, and smart-entry write boundary. Implementing all of that as one task would leave the application broken between commits and make failures difficult to isolate.

The work is therefore split into six ordered, independently verifiable plans. Each plan must keep Docker startup and the existing authenticated product usable.

## Delivery Order

| Phase | Deliverable | Depends On | Product Proof |
| --- | --- | --- | --- |
| 1 (complete) | SQLite foundation and migration runtime | None | App starts against a versioned local database without changing current API behavior |
| 2 | Versioned profile and deterministic daily targets | Phase 1 | New users confirm profile, overall goal, activity and four daily targets |
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

The completed Phase 1 plan is:

- `docs/superpowers/plans/2026-07-19-sqlite-records-foundation.md`

Plans 2-6 are written after the preceding phase lands so their exact paths and signatures match the code actually delivered. This prevents speculative plans from drifting from the repository while preserving the approved order and boundaries above.
