---
inventory-delta:
  packages/hive-conductor/tests/e2e: +0
---

# 1048 — Workspace Home shell (default landing + projections UI)

Adds the first frontend slice of Workspace Home (#1048):

- `frontend/src/pages/Home.tsx` — layout + projections read, pin toggle, honest
  Goals unavailable copy, select-to-open via projection `href`
- `frontend/src/lib/home.ts` — shared wire types/path helpers (typed-client safe)
- `App.tsx` index → `/home`; `AppShell` nav entry; Dashboard retained
- `tests/e2e/workspace-home-shell.spec.ts` — Playwright (index redirect, API
  consumption, pin POST, Legacy Dashboard link)
- `navigation-coverage.spec.ts` + `docs/route-inventory.md` updated for Home

The count above does not move: `check-suite-inventory.py` collects this suite
with pytest (`test_*.py` only). Playwright `*.spec.ts` files run in
`hive-conductor-e2e-ui` instead, so the +0 block is ledger legibility only.
