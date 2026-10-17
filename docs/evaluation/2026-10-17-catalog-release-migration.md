# Catalog release migration acceptance — 2026-10-17

## Result

Explicit `catalog_release=zh-CN.2026-10-17.1` is implemented for bundled localized catalogs. Upstream dataset versions and row identities are unchanged; the generic immutable ledger was not relaxed. The retained main database has been migrated without deleting old ledger entries or rewriting historical business records.

Host `/health/ready` returned `ready`, database `ok`, schema 6, failed catalog imports 0, failed legacy migrations 0. Previously readiness was degraded with two checksum conflicts. Frontend HTTP returned 200; both containers were healthy and the sole active backend data mount was `D:\code\vibe-coding\fitlife-agent\backend\data`.

The official `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1` also completed with exit code 0 and `FitLife Agent is ready`; repeated startup no longer times out on the catalog conflict.

## Verification evidence

- TDD: 31 initial failures before implementation; final focused catalog/ledger/builder/startup/readiness suites: **94 passed**, 56.96 seconds.
- All backend cases were verified in two environment groups: **1950 business tests passed** in 800.27 seconds and **6 configuration tests passed** in 1.48 seconds. Both JUnit reports have zero failures, errors, and skips; total 1956 cases.
- Reports: `.tmp/catalog-release-business-full.xml`, `.tmp/catalog-release-config-final.xml` (ignored local artifacts).
- The first isolated attempt lacked synthetic anonymous demo files; the existing sample generator supplied them only under `.tmp/`. A subsequent mixed-environment attempt exposed that the `.env` precedence test cannot run with a global DATA_DIR override. These incomplete attempts were stopped, not reported as passing. The final two groups cover every backend case without exposing production data to tests.
- Independent specification review: compliant. Independent final code-quality review: ready, no critical or important findings. One optional follow-up is a test tying committed envelope labels directly to the shared release constant; current artifacts match and the builder emission is tested.
- Frozen source-file hashes were unchanged through the complete final regression.
- Both committed bundled catalogs changed by exactly one envelope line; upstream record payloads were not rewritten.

## Retained-data checks

Both the isolated rehearsal and actual formal migration compared contents, not just row counts:

- 20 non-catalog business tables unchanged, including profiles, records, drafts, budgets, favorites, usage, and migration metadata.
- Private catalog rows, private aliases, and private search entries unchanged.
- Public source-derived IDs and upstream dataset versions unchanged.
- Every previous import-ledger row unchanged; exactly two new completed release entries.
- Active public foods: 2128. Active public exercises: 754 (750 bundled free-exercise-db records plus four retained legacy cardio records).
- SQLite integrity `ok`, foreign-key errors 0, active public rows missing FTS entries 0, schema still 6.
- A second real startup on the rehearsal copy preserved the full catalog/search digests and all other checked facts.
- The 18 account/configuration files, including the existing deployment encryption configuration, retained the same combined content digest through cutover. No keys or private row contents are included in this report.

Final backup after backend writers were stopped:

```text
.local-backups/pre-catalog-release-cutover-20261017/fitlife.sqlite3
bytes: 6668288
SHA-256: 56f0f346da97a98021c3b2360085c45c698fac81864b863a5c0dc403c7d655cb
integrity_check: ok
```

The preceding pre-implementation backup has the same checksum. Backups remain ignored, outside Docker build context, and available for recovery. No database, backup, `.env`, credential, or private fixture is committed.

## Scope and operational cleanup

The old worktree's user data was explicitly discarded by the user. Its scoped administrator cleanup logged `CLEANUP_OK`; the directory is absent and Git lists only main and the primary worktree. Twelve fully merged remote development branches were removed with expected-ref guards, and actual remote heads were re-read to confirm main was the only branch. Final source publication is verified from Git after committing this acceptance record; this document does not claim an unperformed future push.

Agent-created copies containing retained user data were removed after successful validation: `.tmp/catalog-release-rehearsal/` and `.tmp/retained-catalog-diagnosis-20261017.sqlite3` (including any sidecars). The formal database and verified recovery backups remain; synthetic test outputs do not represent additional active user databases.

No frontend source, model configuration, schema version, or feature-enable default was changed. Interactive Entry remains subject to its existing explicit deployment switch. This repair adds no runtime model calls or second active database.
