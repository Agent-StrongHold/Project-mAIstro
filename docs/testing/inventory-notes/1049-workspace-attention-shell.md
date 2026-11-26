---
inventory-delta:
  packages/hive-conductor/tests/e2e: +0
---

# 1049 — Workspace Attention shell (read-only UI)

Adds the first frontend slice of Workspace Attention (#1049):

- `frontend/src/pages/Attention.tsx` + `lib/attention.ts`
- `App.tsx` route `/attention`; `AppShell` nav entry
- `route-inventory.md` + `navigation-coverage.spec.ts`
- `tests/e2e/workspace-attention-shell.spec.ts`

Backend GET projection was already shipped; this PR does not add defer/answer
UI or MERGE Messages/Optimizer. Playwright specs do not move the pytest
collected e2e count (+0 by construction).
