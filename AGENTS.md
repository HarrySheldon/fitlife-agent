# Execution rules

- Use valid Windows PowerShell commands; use native filesystem cmdlets with `-LiteralPath`.
- Before Python tests, verify pytest using the existing project interpreter (`.venv\Scripts\python.exe -m pytest --version`), then run tests with that interpreter.
- Preserve unrelated uncommitted files and changes.

# Database isolation

- Before creating a development branch or worktree, identify the main checkout's active database path and create a timestamped backup with `scripts/backup_sqlite.py --output <absolute-backup-path>` using the main checkout's interpreter and configuration. Store backups under the main checkout's ignored `.local-backups/` directory. Verify the command succeeds, SQLite integrity is `ok`, and record the backup path and checksum before proceeding.
- Initialize development data from that backup in a separate data directory. Configure development and tests to use their own data directory/database; verify the resolved paths or Docker bind mounts differ from the main checkout before starting them. Include any separate runtime database when preserving run history is required; never copy a live SQLite database as an ordinary file.
- Keep account configuration and encryption keys consistent with the selected data copy. Keep databases, exports, backups, `.env`, and credentials out of Git; avoid printing private data or keys.
- Before integration or schema migration, back up the retained main database again. Retain main data unless the user explicitly chooses a data migration; code merges do not merge SQLite contents.
- Remove development data only after its code is safely committed and merged and the user has approved discarding that data. Verify remaining running services use the main data directory.
