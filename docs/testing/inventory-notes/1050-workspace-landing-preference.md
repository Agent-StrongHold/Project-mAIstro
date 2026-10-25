---
inventory-delta:
  packages/hive-conductor/backend/tests: +11
  packages/hive-conductor/tests/e2e: +0
---

# 1050 — Workspace landing + restore preferences (first slices)

Adds explicit Workspace product preferences for cutover (#1050):

- `PROFILE_SCHEMA` lists `workspace_default_landing` and
  `workspace_restore_aggressiveness` so chat `profile_set` and the Profile
  panel share one field each on the canonical profile store
- `services/workspace_preferences.py` — allow-lists + write validation (400)
- `frontend/src/lib/landing.ts` — client normalize helpers
- `frontend/src/lib/profile.ts` — Profile transport + `ProfilePayload` (typed-client)
- `DefaultLandingRedirect` — authenticated index reads the landing preference
- Profile selects PATCH `/v1/profile` for both fields
- `backend/tests/test_workspace_landing_preference.py` — schema, round-trip,
  per-user, refuse invalid writes, normalize helpers, HTTP 400 on PUT/PATCH,
  chat `profile_set` tool error (11 cases)
- `tests/e2e/workspace-landing-preference.spec.ts` — Playwright (index
  steering, Profile writes, API 400). Count stays +0: suite inventory collects
  pytest `test_*.py` only; Playwright runs in `hive-conductor-e2e-ui`.
