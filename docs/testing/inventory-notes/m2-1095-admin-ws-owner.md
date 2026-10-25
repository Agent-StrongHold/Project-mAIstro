---
inventory-delta:
  packages/maistro-server/tests: +1
---

# m2-1095 — admin-only WS owner gate

`ws._ws_owner_id` shares the admin-only deployment gate the issue fixed in the
rate limiter and the diagnostics endpoints (#1095): `API_KEYS` empty with
`ADMIN_API_KEYS` set is auth-enabled, so the stream owner is the resolved
admin principal. The existing `TestWsOwnerId` cases only exercised `API_KEYS`
deployments, so a regression of the gate back to
`if not settings.api_keys: return "dev"` would have shipped green. The new
`test_admin_only_deployment_is_auth_enabled` pins the distinguishing
behavior — the admin bearer resolves to `ops`, while an absent or invalid
bearer is rejected rather than served as `dev` (every assertion returns
`"dev"` under the pre-#1095 gate).
