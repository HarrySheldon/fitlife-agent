# Data Sources, Migration, And Recovery

## Authoritative Stores

| Data | Authenticated user | Anonymous demo |
| --- | --- | --- |
| Identity and legacy profile projection | `backend/data/users.json` and per-user JSON | `backend/data/user_profile.json` |
| Profile, goal, targets, catalogs, drafts, meals, workouts | `backend/data/fitlife.sqlite3` | Bundled files and top-level CSV |
| Model connection and preferences | Per-user encrypted/local settings files | Deployment environment |

After `legacy_csv_v1:<user_id>` is completed, the record router always reads and writes that user's meal and workout records in SQLite. Later edits to the retained CSV files do not switch the user back. A failed or incomplete migration leaves that user file-backed.

## Bundled Catalogs

- Foods: `backend/data/catalog/foods.zh-CN.v1.json`, audited USDA FoodData Central records, `CC0-1.0`.
- Strength exercises: the `free-exercise-db` partition in `backend/data/catalog/exercises.zh-CN.v1.json`, `Unlicense`.
- Cardio activities: the 2024 Adult Compendium partition in the same file; attribution and source URLs are stored per record.

Runtime search uses local SQLite only. Each source partition is fully validated and canonically checksummed before mutation. A completed source/version rejects checksum drift, a repeat checksum is skipped, and a failed update rolls back catalog and FTS changes together.

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
