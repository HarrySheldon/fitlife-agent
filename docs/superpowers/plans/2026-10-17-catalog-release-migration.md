# Catalog Release Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish localized catalogs without reusing immutable upstream import identities or rewriting user history.

**Architecture:** Keep upstream versions and row identities unchanged. An explicit catalog release qualifies only the import-ledger identity; missing release retains legacy semantics. Keep source-partition transactions and checksum-drift rejection intact.

**Tech Stack:** Python, SQLite, pytest, deterministic JSON catalogs, Docker Compose, PowerShell.

**Workspace:** User requested one main branch/worktree; perform the scoped repair on main and isolate all test data. Preserve unrelated untracked files. The main database is backed up under ignored `.local-backups/pre-catalog-release-20261017/fitlife.sqlite3` before implementation.

## Task 1: Release-qualified catalog imports (one cohesive code task)

Files:
- Create `backend/infrastructure/catalog/release.py` and `backend/tests/infrastructure/test_catalog_release.py`.
- Modify `backend/infrastructure/catalog/seed_foods.py`, `seed_exercises.py`, `scripts/build_localized_catalogs.py`.
- Modify only the envelopes of `backend/data/catalog/foods.zh-CN.v1.json` and `exercises.zh-CN.v1.json`.
- Extend `backend/tests/catalog_receiver/test_build_localized_catalogs.py` and update existing ledger-version assertions only where bundled releases intentionally change the key.
- Document the release authoring/compatibility rules in `docs/data-sources.md`.

- [x] Write synthetic regressions first, covering each importer: import a minimal legacy payload; change its display name under `catalog_release=zh-CN.2026-10-17.1`; require success, stable IDs/upstream versions, retained original ledger, preserved private catalog rows and historical meal/workout snapshots. Require a second import to skip, mutated same-release content to fail without catalog/FTS/ledger mutation, and a new explicit release to succeed.
- [x] Parametrize present-invalid releases (`None`, empty/whitespace, numeric/bool, slash/newline, overlong strings); require rejection before any mutation. Confirm absent release preserves the legacy ledger key and checksum guard.
- [x] Run the new test file with `.venv\Scripts\python.exe -m pytest backend/tests/infrastructure/test_catalog_release.py -q --basetemp .tmp/catalog-release-red -p no:cacheprovider`; record the actual RED result before implementation.
- [x] Add a small release helper. Expose `BUNDLED_CATALOG_RELEASE = "zh-CN.2026-10-17.1"` and `catalog_import_version(payload, dataset_version)`. A missing field returns `dataset_version`; a present field must fully match `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`, otherwise raise `ValueError("CATALOG_RELEASE_INVALID")`. Qualify explicit releases structurally with a reserved prefix and JSON-encoded `[dataset_version, release]`, rather than appending ambiguous delimiters or auto-versioning by checksum.
- [x] Validate/resolve the ledger version before mutation in both seed importers; pass it only to `CatalogImportLedger.run`. Continue calculating partition checksums from unchanged upstream records/version. Do not alter the generic ledger or source-derived row IDs.
- [x] Declare `catalog_release` in both bundled envelopes and in both outputs of the deterministic builder, using the shared release constant for generator output. Preserve every upstream version and record payload.
- [x] Require builder tests to assert the emitted release; document that changing bundled content requires an explicit release bump and that raw receiver payloads remain legacy-compatible.
- [x] Run new tests plus existing food/exercise seed, ledger, localized-builder, startup and readiness suites. Follow with independent spec review and quality review; fix and rerun until no important findings remain.

## Task 2: Rehearse and deploy against retained data

- [x] Verify the pre-migration backup's SQLite integrity and SHA-256. Copy this offline backup to ignored `.tmp/catalog-release-rehearsal/fitlife.sqlite3`, never copy a live SQLite file as an ordinary file.
- [x] On the copy, run the real startup path using main's existing data directory for read-only legacy account discovery. Compare content digests of all non-catalog business tables, private rows, public source-derived IDs, old ledger rows, and FTS consistency before/after. Require startup `ready`, schema 6, expected public source counts, and a second startup to be idempotent.
- [x] Run every backend test using two environment groups: `backend/tests --ignore=backend/tests/test_config.py` with synthetic samples in isolated DATA_DIR, and `backend/tests/test_config.py` in a separate process without global DATA_DIR/SQLITE_DATABASE_PATH overrides. The configuration tests intentionally test their own temporary `.env` precedence. Disable live model calls for the business group and persist both JUnit reports under `.tmp/`.
- [x] Stop backend writers, take a final consistent verified backup, build/recreate only the backend with the retained main data mount, then verify host `/health/ready` is `ready` and unchanged historical business digests. Keep the frontend and account settings intact.
- [x] Record actual validation results and backup path/checksum in an acceptance document without private row contents, credentials, or live data fixtures.

## Task 3: Finish synchronization and cleanup

- [x] Verify administrator cleanup log contains `CLEANUP_OK` and the retired worktree directory is absent. Git must report main as the sole local branch and worktree.
- [x] Check staged paths explicitly exclude databases/backups/credentials; commit the repair and docs after fresh tests. Implementation and live acceptance committed as `f7e2318`.
- [ ] Fetch and compare remote, push main without force, and delete only fully merged remote development branches using expected-ref checks. Re-read actual remote heads and require main/origin-main equality before reporting remote completion; report any genuine network blocker separately.

Remote cleanup is complete: all 12 merged development branches were deleted with expected-ref guards and actual heads re-read as main only. Publication of this repair remains unverified: subsequent ordinary, HTTP/1.1, and IPv4 push attempts failed with connection reset/timeout. Cached origin/main remains `120f7ca`; do not report release-ready or synchronization until a fresh remote check succeeds.
