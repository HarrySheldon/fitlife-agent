# Controlled Imports And Legacy Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make bundled catalog updates and legacy per-user CSV cutover licensed, checksummed, idempotent, recoverable, observable, and safe to run automatically at startup.

**Architecture:** Catalog adapters validate complete source partitions before a ledger-controlled transaction mutates SQLite. Legacy CSV migration creates a timestamped read-only archive before a single reconciliation transaction; a routing repository reads SQLite only after that user's completed ledger row and otherwise preserves the file-backed path. Agent/report/plan consumers depend on the routing repository, while model invocation boundaries remain unchanged.

**Tech Stack:** Python 3.12+, FastAPI lifespan, SQLite WAL/backup API, stdlib `csv`/`zipfile`/`logging`, pandas compatibility projections, pytest, Docker Compose.

---

## Open-Source Practice Baseline

- [Prisma migration persistence](https://github.com/prisma/prisma-engines/blob/main/schema-engine/ARCHITECTURE.md) records checksum, start/finish state and failure logs in `_prisma_migrations`; Phase 6 mirrors that immutable identity and explicit terminal status.
- [Flyway validation](https://github.com/flyway/flyway/blob/main/documentation/Reference/Commands/Validate.md) treats an applied migration checksum mismatch as a validation failure rather than silently rewriting history.
- [SQLite online backup](https://github.com/sqlite/sqlite/blob/master/src/backup.c) copies a consistent database image through the backup API; Python's `Connection.backup` is used for release backups and CSV sources are separately archived with a manifest.
- [sqlite-utils upsert](https://github.com/simonw/sqlite-utils/blob/main/sqlite_utils/db.py) requires stable primary keys for deterministic upserts; catalog rows continue to use source identity-derived UUIDs and `(source_name, source_record_id)` uniqueness.

## Confirmed Boundaries

- Runtime catalog reads use local SQLite only; no runtime external API calls are introduced.
- A catalog import failure leaves the prior active source partition and FTS rows unchanged.
- A legacy migration failure leaves the original CSV files untouched and keeps that user on file-backed reads.
- A completed legacy cutover never reruns the same migration version and never switches back because the old source later drifts.
- Unknown legacy values remain absent in structured child rows and are preserved only as raw provenance; Agent is never called during import or migration.
- Signed-in CSV uploads become explicit transactional imports after cutover instead of replacing the authoritative data source.
- Account data export, recipes, barcode/image recognition, PostgreSQL and background model calls remain excluded.

## File Map

**Catalog imports**

- Create `backend/infrastructure/catalog/import_ledger.py`: checksum/status lifecycle and transaction callback.
- Modify `backend/infrastructure/catalog/seed_foods.py`: USDA adapter validation and ledger-controlled source import.
- Modify `backend/infrastructure/catalog/seed_exercises.py`: per-source adapter partitions and ledger-controlled import.
- Modify catalog seed tests and add `backend/tests/infrastructure/test_catalog_import_ledger.py`.

**Legacy migration and cutover**

- Create `backend/infrastructure/migration/legacy_csv.py`: parse, archive, import, reconcile and ledger orchestration.
- Create `backend/infrastructure/repositories/sqlite_fitness_repository.py`: SQLite-to-legacy DataFrame compatibility and deterministic append adapter.
- Create `backend/infrastructure/repositories/cutover_fitness_repository.py`: per-user completed-ledger routing.
- Modify `backend/infrastructure/sqlite/schema.py`: add `data_migrations.user_id` and its index.
- Modify `backend/infrastructure/repositories/sqlite_profile_target_repository.py`: delete user migration ledger rows.
- Modify report/plan/Agent/dashboard/calendar composition roots to use the routing repository.
- Modify `backend/api/upload.py`: authenticated transactional CSV import; anonymous demo behavior remains file-backed.

**Startup and release**

- Create `backend/infrastructure/startup.py`: ordered migrations, controlled imports, per-user cutover and structured event summaries.
- Modify `backend/main.py`, `backend/api/health.py`, `docker-compose.yml`, README and data-source documentation.

## Task 1: Catalog Import Ledger And Source Adapters

- [x] Add tests proving first import completes a ledger row, identical checksum skips, same version/different checksum fails, failed callbacks preserve old rows, and a newer successful version deactivates only missing rows in its source partition.
- [x] Implement `CatalogImportLedger.run(source_name, dataset_version, checksum, callback)` with `BEGIN IMMEDIATE`, terminal `completed` status in the mutation transaction, and sanitized `failed` status in a separate recovery transaction.
- [x] Refactor food and exercise seeds to validate complete source documents before opening a write transaction and to compute canonical source-partition checksums.
- [x] Preserve existing result counters and expose `skipped` without changing catalog repository contracts.
- [x] Run focused catalog/schema tests and commit `feat: ledger controlled catalog imports`.

## Task 2: Read-Only Legacy Backup And Atomic Migration

- [x] Add schema migration 3 with nullable `data_migrations.user_id`, an index, and invariant tests.
- [x] Add fixed CSV fixture tests for grouped meal labels, one workout session per old row, unknown strength/cardio values, stable `legacy_source_id`, source/date/count/total reconciliation and no Agent usage.
- [x] Implement strict parsers using `csv.DictReader`; validate required headers and dates, preserve raw row identifiers, and reject negative nutrition/duration values before writing.
- [x] Create a timestamped ZIP under `users/<user_id>/legacy-backups/` containing source bytes and `manifest.json`; calculate archive SHA-256 and mark the final archive read-only before database mutation.
- [x] Import all rows in one SQLite transaction, reconcile row counts, date bounds and nutrition/duration totals, then mark `legacy_csv_v1:<user_id>` completed in that transaction.
- [x] On parse/write/reconciliation failure, roll back formal rows, keep CSVs untouched, record a sanitized failed ledger row and return a recoverable result.
- [x] Delete user-scoped migration ledger rows during account deletion; the existing user-directory deletion removes that user's archives.
- [x] Run focused migration/account-deletion tests and commit `feat: migrate legacy csv with verified backups`.

## Task 3: Per-User Cutover And CSV Upload Compatibility

- [x] Test that incomplete/failed migration reads and writes use `FileFitnessRepository`, while completed migration uses SQLite and never falls back because old CSV changes.
- [x] Implement `SQLiteFitnessRepository` projections with exact legacy DataFrame columns so deterministic report/plan/Agent analyzers remain unchanged.
- [x] Implement `CutoverFitnessRepository` routing by completed user-scoped migration ledger status; anonymous demo calls remain file-backed.
- [x] Replace direct `FileFitnessRepository` construction in report, plan and Agent composition roots; update dashboard/calendar helpers to use the same repository boundary for authenticated users.
- [x] Import signed-in meal/workout CSV uploads directly and transactionally with checksum idempotency; archive the submitted bytes, return imported/replayed counts, and refresh Logbook from SQLite.
- [x] Verify no upload, startup, read or write path invokes a model and commit `feat: switch completed users to sqlite records`.

## Task 4: Startup, Readiness And Docker Hardening

- [x] Test startup ordering: schema migration, catalog imports, legacy cutover, then request serving; catalog/legacy failures are logged and do not destroy the last usable source.
- [x] Add structured events containing operation, version, status, counts, duration and checksum prefix only; never log CSV rows, tokens, API keys or model prompts.
- [x] Add `/health/ready` database `quick_check`, schema version, failed import count and failed legacy migration count; database failure returns `503`, recoverable migration failures return `200` with `degraded` status.
- [x] Add backend/frontend Compose health checks and make frontend depend on backend health; keep configurable host ports and persistent `backend/data` volume.
- [x] Add startup/readiness/Compose tests and commit `feat: harden startup and readiness checks`.

## Task 5: Phase Verification And Release Evidence

- [x] Run catalog, migration, cutover, upload, health and Agent-boundary focused tests.
- [x] Run the complete backend suite with an accessible `--basetemp` and the complete frontend suite.
- [x] Run `tsc -b`, production frontend build and `docker compose config --quiet`.
- [x] Rebuild Docker, verify both health checks and restart recovery when Docker Desktop is available.
- [x] Browser acceptance: migrated legacy account, catalog/form flow without a model, explicit smart-entry Agent action, signed-in CSV upload replay, desktop and `390x844` no-overflow/console-error checks when local browser access is permitted.
- [x] Add `docs/data-sources.md`, backup/recovery instructions, exact verification evidence and roadmap status.
- [x] Run a standards/spec/security review covering license boundaries, checksums, rollback, source routing, ownership, logs and excluded features.
- [x] Commit `docs: verify controlled imports and legacy cutover`, push the clean branch and verify local/remote SHA equality.

### Verification Evidence

- Backend: `770 passed`, one known Starlette/httpx deprecation warning, `74.12s`.
- Frontend: `28` files and `157` tests passed, `33.84s`; production build transformed `2466` modules in `20.00s` with the existing chunk-size warning.
- Dependencies: production-only and complete `npm audit` runs both reported zero vulnerabilities.
- Compose: `docker compose config --quiet` passed. An isolated final rebuild exposed backend `18000` and frontend `13000`; readiness reported `ready`, schema `3`, zero catalog failures and zero legacy migration failures. Both health checks returned to `healthy` after `docker compose restart`.
- Browser: a dedicated old CSV account surfaced `Legacy tofu` (`288 kcal`) and `Legacy squat` (`45 min`) after startup cutover. A local catalog meal confirmed without a model; a user-triggered unresolved smart-entry analysis returned the model-configuration error; the same signed-in meal CSV uploaded successfully twice. Desktop `1280x720` and mobile `390x844` had no document-level horizontal overflow and no console warnings/errors.
- Recovery: `scripts/backup_sqlite.py` produced a verified `552960` byte image with SHA-256 `ff33137b3457c7dc1da34f48beae48b79977184ef7c858ecb3bf5968967d9c45`. Deleting the migrated acceptance account removed its read-only backup and invalidated subsequent login with `401`.
- Review: no open Critical or Important findings. License/attribution partitions, immutable checksums, transaction rollback, sticky source routing, user ownership, sanitized logs, explicit Agent invocation and excluded-feature boundaries were checked. The review found and fixed Windows deletion of read-only migration archives; `26` focused deletion tests and the complete backend suite cover the correction.

## Completion Criteria

- Catalog source versions are validated, checksummed, ledgered and rollback-safe.
- Legacy CSV is archived before mutation, migrated once, reconciled and retained unchanged.
- Only users with completed cutover rows read/write SQLite through legacy report/plan/Agent boundaries.
- Failed or incomplete cutovers continue using the old file source without Agent fallback.
- Signed-in CSV upload remains a usable explicit input path after cutover.
- Health/readiness and structured logs expose operational state without sensitive content.
- Backend, frontend, build, Compose, Docker and browser gates have current evidence or a precisely documented external blocker.
