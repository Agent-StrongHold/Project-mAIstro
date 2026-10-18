---
inventory-delta:
  packages/hive-conductor/backend/tests: +7
---

The authorization tests cover the live no-store capability contract for admin and zero-permission users, assigned/elevated/expired/revoked transitions, and the `HIVE_ELEVATION_TTL_SECONDS` clamp (an override may only shorten the 15-minute default, never extend it — the browser E2E drives a real grant to its server-side expiry through it).

Browser E2E (`tests/e2e/authorization.spec.ts`) covers roles, deep links, direct URL access, scoped grants, self-elevation, assignment revocation mid-elevation, and expiry against a real deployment. It is not part of the pytest inventory: `packages/hive-conductor/tests/e2e` is deliberately excluded from testpaths (root `pyproject.toml`) and runs through CI's `hive-conductor-e2e-ui` job instead. Task-completion revocation stays machine-tested at the API level (`test_api.py::test_elevation_revoked_on_task_completion`), because the E2E harness never provisions the maistro-server that `POST /v1/tasks` proxies to (same disposition as the skipped `test_tasks` there).

The frontend is a convenience projection of `/v1/auth/capabilities`; the API remains the authority, which the E2E asserts directly (nav hides what the API still 403s, and an elevated call 403s again the moment the assignment is revoked).
