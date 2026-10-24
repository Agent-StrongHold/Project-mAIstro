---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
  packages/hive-conductor/tests/e2e: +0
---

# 1050 — Workspace default landing preference (first slice)

Adds the explicit default-surface preference for Workspace cutover (#1050):

- `PROFILE_SCHEMA` lists `workspace_default_landing` so chat `profile_set` and
  the Profile panel share one field on the canonical profile store
- `frontend/src/lib/landing.ts` — allow-list + safe path resolve (Home baseline)
- `DefaultLandingRedirect` — authenticated index reads the preference
- Profile select PATCHes `/v1/profile` with that field
- `backend/tests/test_workspace_landing_preference.py` — schema + store round-trip
- `tests/e2e/workspace-landing-preference.spec.ts` — Playwright (index steering,
  Profile write). Count stays +0: suite inventory collects pytest `test_*.py`
  only; Playwright runs in `hive-conductor-e2e-ui`.
