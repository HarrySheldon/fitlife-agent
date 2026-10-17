# Data Sources, Migration, And Recovery

## Authoritative Stores

| Data | Authenticated user | Anonymous demo |
| --- | --- | --- |
| Identity and legacy profile projection | `backend/data/users.json` and per-user JSON | `backend/data/user_profile.json` |
| Profile, goal, targets, catalogs, drafts, meals, workouts | `backend/data/fitlife.sqlite3` | Bundled files and top-level CSV |
| Model connection and preferences | Per-user encrypted/local settings files | Deployment environment |

After `legacy_csv_v1:<user_id>` is completed, the record router always reads and writes that user's meal and workout records in SQLite. Later edits to the retained CSV files do not switch the user back. A failed or incomplete migration leaves that user file-backed.

## Bundled Catalogs

- Foods: `backend/data/catalog/foods.zh-CN.v1.json`, 2,128 Taiwan FDA Food Nutrient Database records, `Taiwan Government Open Data License 1.0`.
- Exercises: `backend/data/catalog/exercises.zh-CN.v1.json`, 750 strength and cardio records from `free-exercise-db`, `Unlicense`. Attribution and source details are stored per record.

Runtime search uses local SQLite only. Each source partition is fully validated and canonically checksummed before mutation. A completed source/version rejects checksum drift, a repeat checksum is skipped, and a failed update rolls back catalog and FTS changes together.

### Authoring Catalog Releases

The bundled envelopes declare `catalog_release: "zh-CN.2026-10-17.1"`. This identifies our published localization separately from the upstream `dataset_version`. When changing published names, aliases, taxonomy, provenance, or other normalized content, bump `BUNDLED_CATALOG_RELEASE` in `backend/infrastructure/catalog/release.py`, regenerate both catalogs with `scripts/build_localized_catalogs.py`, and review the generated changes. Release labels must fully match `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`; do not reuse a completed release for changed content. Do not alter upstream dataset versions to disguise localization changes.

Only the import ledger key is qualified: `catalog-release:` followed by a compact JSON pair `[upstream_version, release]`. Catalog records keep upstream versions and stable source identities, while historical meal/workout snapshots retain their recorded values. Explicit releases reject an upstream version already beginning with the reserved prefix, avoiding nested qualified identities. Raw receiver payloads without `catalog_release` retain the exact legacy import identity and checksum behavior. Since legacy versions accept arbitrary nonblank strings, a legacy value could resemble a qualified key; the unchanged ledger rejects checksum drift on any completed-key collision. Never delete or rewrite completed ledger rows to force an import.

## Legacy CSV Cutover

Startup applies schema migrations, imports bundled catalogs, then visits registered users. Before any legacy record mutation it writes:

```text
backend/data/users/<user_id>/legacy-backups/legacy_csv_v1-<timestamp>-<checksum>.zip
```

The ZIP contains the exact `meals.csv` and `workouts.csv` bytes plus `manifest.json` with file sizes and SHA-256 values. The completed archive is read-only. Migration groups meal rows by date and meal label, creates one training session per workout row, preserves raw values as provenance, reconciles counts/date bounds/nutrition/duration totals, and commits records plus the user ledger row atomically. It never calls a model.

Signed-in CSV uploads after cutover are archived under `users/<user_id>/imports/`, imported transactionally, and replayed idempotently by content checksum. Anonymous and not-yet-cutover upload behavior remains file-backed.

## Backup

Create a consistent SQLite image while the service is running:

```powershell
.venv\Scripts\python.exe scripts\backup_sqlite.py --output backups\fitlife.sqlite3
```

The command uses SQLite's backup API, runs `PRAGMA quick_check` on the copied database, replaces the destination atomically, and prints its path, byte count, and SHA-256. Back up these items together:

- the verified SQLite image;
- `backend/data/users.json`;
- per-user JSON/settings files;
- generated `legacy-backups` and `imports` directories;
- the deployment `SETTINGS_ENCRYPTION_KEY` in a secret manager, never in the backup directory or Git.

## Recovery

1. Stop backend writers with `docker compose down` or stop Uvicorn.
2. Keep the damaged `backend/data` directory as forensic evidence; do not overwrite it in place.
3. Verify the selected SQLite backup SHA-256 against the value printed at backup time.
4. Restore the database to the configured `SQLITE_DATABASE_PATH` (default `backend/data/fitlife.sqlite3`) and restore `users.json` plus per-user settings from the same backup point.
5. Preserve existing legacy ZIP files. Extract a ZIP only when deliberately rolling a user back before cutover; do not edit a completed migration ledger to force automatic fallback.
6. Start the backend and require `GET /health/ready` to report database `ok`, the expected schema version, and either `ready` or an explained `degraded` state.
7. Verify one migrated user's Logbook totals and one deterministic report before enabling Agent actions.

If the encryption key is lost, encrypted API keys cannot be recovered from data backups. Deterministic product features remain available; users must save model credentials again under a new deployment key.
