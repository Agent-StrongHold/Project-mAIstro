---
inventory-delta:
  packages/maistro-core/tests: +1
---

Issue #1057 repair round (develop sync of the #1180 task-stream change into
the delegation branch): one test in
`packages/maistro-core/tests/tasks/test_idempotency.py` pins the last-resort
replay path to the delegated evidence.

- `test_a_delegated_replay_without_any_receipt_reconstructs_the_evidence` —
  the prior audit's executed replay simulation showed the claim-tier
  reconstruction answering `alice None None user`: the claim's stored request
  carried only the owner id, dropping the service principal, delegation id
  and actor kind. The fix (queue admission persists all three into the claim
  and `_replay_receipt` echoes them) is held in place by a restart scenario
  where neither the live in-memory receipt nor the durable `TaskRecord` row
  survives — a fresh queue over the same claim store must reconstruct a
  receipt that still names `conductor` / `delegation-123` / `user`.

Same repair round, no test count change: merging develop's persistent sync
client (#1180) into `MaistroServerTaskBackend` kept the signed delegation
envelope on `get`/`get_async`/`list_tasks`
(`packages/hive-conductor/backend/adapters/task_backend.py`), and the
develop-side fixtures were updated to the #1057 contract —
`_ScopedBackend` grew the protocol's `get_async`, develop's scoped-probe
stub accepts the `user_id` kwarg, and `test_task_stream_event_loop`'s
backend is constructed with an explicit `delegation_key` so the scoped
stream satisfies fail-closed instead of bypassing it.

Also this round, no test count change: develop's #1182 made
`wire_execution_spine` read settings at wiring time, which froze the
settings cache during the `durable_spine` fixture — before the delegated
admission tests pin `API_KEYS`/`TASK_DELEGATION_KEY` in their bodies. The
two-user ownership test then authenticated as the auth-disabled `dev`
principal and failed the delegation service-principal match (403). Both
delegation tests in
`packages/maistro-server/tests/api/test_task_workspace_scope.py` now follow
the repo idiom already used by `test_rate_limit.py`: `setenv` followed by
`get_settings.cache_clear()`, so the forged-envelope test refuses for the
match it names rather than by accident.
