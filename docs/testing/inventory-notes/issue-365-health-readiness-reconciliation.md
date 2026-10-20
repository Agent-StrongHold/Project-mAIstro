---
inventory-delta:
  packages/maistro-server/tests: +2
---

# #365 / #1567 readiness-diagnostics reconciliation (develop sync)

Develop's #1567 (`394ff8422`) serves a detailed readiness payload — dependency
`checks`, `effective_resource_policy`, `strike_tracker`, cgroup-v2
`container_limits` — to every caller of `GET /health/ready`. This branch's #365
contract keeps public health minimal. The merge resolution (985c4f781) extends
#1567's own admin-gating of `container_limits` to the whole payload: detail is
served only when API auth is enabled AND the caller presents a valid
admin-scoped bearer token; anonymous, user-scope, wrong-token, and
auth-disabled callers all get the status-only contract
(`{"status": "ok"}` / 503 `{"status": "not_ready"}`).

`test_resource_policy_health.py` (+2 items vs develop: 7 → 9): the develop
anonymous-exposure tests were cut over to admin-authenticated variants; the
withholding test now asserts the whole payload is absent for non-admins, not
just `container_limits`; a new auth-disabled case pins that no authorization
decision means no detail. Root `tests/api/test_health.py` was cut over to the
minimal liveness contract (same item count), closing the twin-file CI red
recorded in the seventh verification.
