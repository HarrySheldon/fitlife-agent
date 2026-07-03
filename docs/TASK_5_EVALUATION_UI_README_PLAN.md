# Evaluation UI and README Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose Evaluation v2 results in the React frontend and update the README so the project is easier to review for AI Agent engineering internship applications.

**Architecture:** The backend eval contract already returns structured checks, grouped metrics, and failure reasons. The frontend will type those fields, derive display-friendly view data in a small helper module, and render the existing Evaluation page without introducing new runtime dependencies. README updates will describe the implemented LangGraph, RAG, optional OpenAI adapter, and Evaluation v2 capabilities honestly.

**Tech Stack:** React, TypeScript, Vite, existing CSS, FastAPI Evaluation v2 API.

---

## References

- OpenAI eval practice: explicit datasets, criteria/graders, repeatable runs, and failure analysis.
- Common agent evaluation dashboards such as LangSmith and Phoenix: surface aggregate metrics, per-case results, traces, and failure reasons.
- Existing project UI style: quiet operational dashboard with metric cards and content panels.

## Acceptance Criteria

- Frontend `EvalResult` types include Evaluation v2 fields: `group_metrics`, per-case `checks`, and `failure_reasons`.
- Evaluation page shows:
  - aggregate metrics;
  - grouped pass rates by expected tool and retrieval requirement;
  - total case count and failed case count;
  - failed case reasons and check details without dumping raw JSON as the primary UI.
- Empty success state is explicit when no cases fail.
- README documents the current implemented feature set, local setup, evaluation artifacts, resume bullets, and safety note.
- Frontend build passes with the existing toolchain.
- Backend eval smoke remains runnable.

## Files

- Modify: `frontend/src/types/index.ts`
  - Add typed Evaluation v2 structures.
- Create: `frontend/src/pages/evaluationViewModel.ts`
  - Add small formatting helpers for percentages, group labels, failed case counts, and check labels.
- Create: `frontend/src/pages/evaluationViewModel.contract.ts`
  - Compile-time contract file included by `tsc` to force Evaluation v2 fields and helper signatures.
- Modify: `frontend/src/pages/Evaluation.tsx`
  - Render aggregate metrics, group metrics, and failed case details.
- Modify: `frontend/src/styles/index.css`
  - Add compact table/list styles for evaluation result panels.
- Modify: `README.md`
  - Replace stale/mojibake-heavy sections with clearer reviewer-oriented project packaging.

## TDD Steps

1. Write `frontend/src/pages/evaluationViewModel.contract.ts` that imports `EvalResult`, `formatRate`, `formatGroupKey`, and `summarizeFailures`, then uses a sample Evaluation v2 payload.
2. Run `npm run build` inside `frontend` and verify TypeScript fails because the new fields/helpers do not exist.
3. Add Evaluation v2 types and `evaluationViewModel.ts`.
4. Run `npm run build` and verify TypeScript passes the contract.
5. Update `Evaluation.tsx` to consume the typed view model and render v2 result panels.
6. Update `frontend/src/styles/index.css` with scoped evaluation styles.
7. Update `README.md` with current architecture, local setup, evaluation usage, and resume bullets.
8. Run:

```powershell
cd frontend
npm run build
cd ..
..\..\.venv\Scripts\python scripts\run_eval.py --limit 5
```

9. Commit and push `feat/evaluation-ui-readme`.
