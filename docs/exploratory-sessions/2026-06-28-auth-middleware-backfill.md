---
date: 2026-06-28
tester: Claude (agent)
area: packages/hive-conductor/backend/middleware/auth.py — AuthMiddleware
charter: "Retroactive backfill: this session predates docs/EXPLORATORY-TESTING.md. Logged now, from the original change, as proof the BACKLOG escalation path works for past findings, not just future ones."
---

## Observations

While designing the adversarial path-matching test suite for `AuthMiddleware.dispatch` (Phase 3,
zero tests existed before), constructing sibling-route probes against the public-path allowlist
surfaced two real bugs in the middleware itself, not just untested-but-correct behavior:

1. **Sibling-prefix confusion.** `_PUBLIC_PREFIXES` used plain `str.startswith(prefix)` for
   `"/v1/auth/login"` and `"/v1/auth/register"` with no trailing-`/` boundary. A sibling path that
   merely shared the string prefix — e.g. a hypothetical `/v1/auth/login-history` route — would
   bypass authentication entirely, since `"/v1/auth/login-history".startswith("/v1/auth/login")`
   is `True`. Live-exploitable because both entries sit inside the `/v1/`-scoped auth gate. Fixed
   by extracting `_matches_public_prefix()` (boundary-safe: exact match or prefix-plus-`/`) and
   moving the two `/v1/auth/...` entries to the already-boundary-safe `_PUBLIC_EXACT` set instead.
2. **Substring-anywhere permission carve-out.** `_required_permission` exempted agent-invoke
   requests from permission gating via `if "/invoke" in path`, a substring-anywhere check, not a
   trailing-segment check. Confirmed via grep across `missions.py`/`agents.py`/`work_items.py`/
   `daily_report.py` that no current route contains `/invoke` as a substring outside the real
   `/{id}/invoke` action — so not live-exploitable today — but the check fails *open* (skips a
   permission gate) rather than closed, making it a latent footgun for any future route name
   merely containing the substring. Fixed to `path.endswith("/invoke")`.

## Findings

| # | Kind | Description | Escalated to | Follow-up test |
|---|------|-------------|---------------|----------------|
| 1 | bug | `_PUBLIC_PREFIXES`'s unguarded `startswith` let a sibling path sharing the `/v1/auth/login` or `/v1/auth/register` string prefix bypass authentication entirely. | `BACKLOG.md#engine-111` | `packages/hive-conductor/backend/tests/test_auth_middleware.py::TestSiblingPrefixConfusionRegressionLock` |
| 2 | bug | `_required_permission`'s `"/invoke" in path` substring check fails open for any future route merely containing `/invoke`, not just the real trailing action segment. | `BACKLOG.md#engine-111` | `packages/hive-conductor/backend/tests/test_auth_middleware.py::TestInvokeSubstringCarveOutBoundary` |
