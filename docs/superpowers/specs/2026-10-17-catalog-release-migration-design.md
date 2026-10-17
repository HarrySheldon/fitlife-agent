# Catalog release migration

Status: Implemented, independently reviewed, and verified against the retained main database on 2026-10-17. Acceptance: `docs/evaluation/2026-10-17-catalog-release-migration.md`.

## Problem and scope

The retained main database contains completed upstream source/version imports. The current localized bundled catalogs have different checksums under those same upstream versions. Startup correctly refuses both imports with `CATALOG_IMPORT_CHECKSUM_MISMATCH`, leaving readiness degraded. This repair must preserve the checksum guard, previous ledger entries, stable catalog IDs, private catalogs, favorites, and historical business records.

## Decision

Introduce an explicit optional `catalog_release` in the normalized catalog envelope. The first bundled release is `zh-CN.2026-10-17.1`. Upstream `dataset_version` in the envelope and every record remains unchanged. A small shared helper validates release labels and derives a release-qualified import-ledger version from the upstream version plus the declared release. Legacy payloads without the field retain their exact existing ledger keys and behavior. An explicitly present invalid value (including null, blank, non-string, or an unsafe label) fails before any mutation.

Encode the upstream-version/release pair structurally under a reserved prefix rather than deriving a release from the checksum. Explicit pairs must be unambiguous and nested qualified upstream identities are invalid. Legacy inputs accept arbitrary nonblank version strings, so their existing namespace cannot be made universally disjoint without changing compatibility or the schema; preserve their exact keys and let the existing completed-ledger checksum guard fail closed on a conflicting key. The bundled upstream versions are ISO date strings. Content changes within the same declared release remain errors. A new published release must be explicitly declared by the catalog author.

Both seed importers use the qualified version only for import-ledger identity. Their row validation, upstream provenance, content hashes, source-derived catalog IDs, source-partition transactions, and FTS maintenance remain unchanged. Old completed ledger entries remain available for audit. No schema migration, ledger deletion, blanket overwrite option, runtime translation, or user-record rewriting is introduced.

The deterministic bundled-catalog builder emits the release field, and both committed bundled envelopes declare the same release. Raw receiver payloads without this field keep their existing behavior; extending receiver release publication is outside this repair.

## Rollout and verification

1. Reproduce the retained-database conflict using an isolated SQLite backup and the real seed importers. Never use private main data as a committed fixture.
2. Add synthetic regression tests: legacy import followed by a new declared release succeeds and preserves the old ledger; a repeat release skips; changed content under that release fails atomically; another explicit release succeeds; invalid labels fail before mutation. Cover both foods and exercises, stable IDs, upstream versions, private rows, and business snapshots.
3. Run existing catalog import, localization build, startup, and readiness tests alongside the new tests. Preserve existing same-version drift rejection tests.
4. Back up the live main database with the SQLite backup API and verify integrity and checksum. Rehearse the new startup import on an isolated copy; compare immutable business-table contents and catalog identities, then run startup again to prove idempotence.
5. Rebuild the backend, restart it against the retained main data, and verify `/health/ready` reports `ready`, database integrity is `ok`, schema remains version 6, both directory imports succeed, and no historical business records changed. Keep the verified pre-migration backup for recovery.
6. Commit and push only source, bundled public catalogs, tests, and documentation. Confirm main equals origin/main. Databases, backups, credentials, and temporary verification outputs remain ignored.

## Independent operational blockers

Remote branch cleanup is permitted only for commits contained in main, with expected-ref checks against concurrent remote updates. Windows ACL-protected residual worktree files may require an administrator; no broad permission change outside the exact retired worktree is permitted. These operations do not justify weakening catalog validation.
