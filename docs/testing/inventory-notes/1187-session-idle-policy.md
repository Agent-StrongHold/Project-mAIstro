---
inventory-delta:
  packages/hive-conductor/backend/tests: +10
---

# #1187 authenticated session idle policy

Ten backend cases in `test_session_idle_policy.py` cover the governed seven-day
absolute and 30-minute idle policy, exact boundary expiry, clock rollback,
observational `whoami` behavior, eligible authenticated activity, rejected HTTP
polling and WebSocket handshakes (`test_rejected_websocket_handshake_does_not_
refresh_idle_expiry` pins the regression where a denied `dags.write` handshake
used to refresh `last_activity_at` before the permission close), absolute-cap
enforcement after refresh, deactivation/reactivation invalidation, and explicit
revocation. The UI policy metadata is asserted without exposing the opaque
session id.

Repair reconciliation (develop merge ba2f1f077 into this branch): the merge
initially dropped the resolved `DagExecutionScope` on the floor when develop's
`authorize_hive_dag_scope` rework met this branch's `_stream_dag_run`
extraction; the scope is now passed through and the full backend suite
(2492 tests) plus formal models (422 with the PostgreSQL-backed I29) pass.
Cross-process race safety is closed as a documented single-writer contract in
ADR-077 ("Serialization authority"): the supported deployment serves the
session store from one process, so the in-process session lock serializes every
expiry/revocation/refresh decision.
