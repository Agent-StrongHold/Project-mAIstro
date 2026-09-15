---
inventory-delta:
  packages/hive-conductor/backend/tests: +32
  packages/maistro-server/tests: +2
---
# 1239-task-scoped-elevation

**+29 `packages/hive-conductor/backend/tests`** — `test_task_elevation_scope.py`
pins the repaired task-scoped elevation contract (#1239). The audit finding:
`routes/auth.py` merged every task's elevation grant into one session-wide
`elevated_permissions` union, and `/v1/auth/elevate` accepted any string as a
task id — so one elevation covered every later request for the session's whole
lifetime, under an id nothing would ever revoke.

The new cases pin each half of the failure mode against the real
`main:app` + `AuthMiddleware` stack:

- **Flattening**: a grant for task A is 403 when the request names task B or
  names no task at all; two live grants never collapse into a union at check
  time; the `whoami` union is display-only and the authorization path
  consumes `elevated_grants` against the named task.
- **Indefinite lifetime**: a grant whose `expires_at` has passed stops
  answering immediately, disappears from `whoami`, and is *pruned from the
  session store* (not merely filtered); a legacy pre-TTL bare-list grant reads
  as expired (fail closed); the recorded bound follows the
  `elevation_grant_ttl_seconds` setting (ADR-028 time-boxed delegation,
  ADR-068 §D short-TTL elevation grant).
- **Task binding**: malformed ids (empty, overlong, whitespace, control
  characters, off-charset) are 422; a grant also requires a real caller-owned
  active task, so unknown, foreign, paused, and terminal tasks are refused.
  Persisted malformed keys are ignored, and HTTP/WS request bindings use the
  same grammar and live-task check.
- **WebSocket parity**: the dag-run socket closes with 1008 without a named
  task or under another task's grant, and reaches the handler only for its
  own task (`?elevated_task=`).
- **TTL ceiling**: the settings model rejects values above one hour and the
  runtime guard caps even a bypassed settings object at that ceiling.

Existing elevation tests were updated to the stronger contract, not relaxed:
every helper that elevates now sends `X-Elevated-Task` on its gated calls,
and the `test_auth_routes.py` permission-contract case now asserts the
cross-task and no-task denials that the old union check would have failed.
The PM Playwright workflow likewise carries its returned task binding on every
protected DAG/optimizer call. Node counts elsewhere are unchanged.
