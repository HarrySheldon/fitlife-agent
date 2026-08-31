# Agent Runtime Phase 1 Verification

The trusted pre-refactor Agent contract baseline contains 67 tests. The repository-wide reference baseline is 990 backend tests.

On Windows, the system temporary directory is not reliably writable for this suite. Every verification command must therefore pass a unique `--basetemp` path inside the worktree. Its parent directory must be created before pytest starts; pytest may remove a prior basetemp during cleanup.

Phase 1 verification uses the project interpreter at `D:\code\vibe-coding\fitlife-agent\.venv\Scripts\python.exe`. The expanded Agent contract run covers at least the trusted 67-test baseline plus the new runtime/workflow contracts. The full backend run is required to remain at 990 passing tests, with the existing Starlette/httpx deprecation warning reported separately.

Fresh phase 1 evidence:

- Expanded Agent/runtime contracts: `76 passed, 1 warning in 3.34s`.
- Complete backend suite (fresh after final typed compatibility-layer review): `990 passed, 1 warning in 477.57s`.
- Static import scan: no `langgraph` or `langchain` references remain in `backend` or `requirements.txt`.
