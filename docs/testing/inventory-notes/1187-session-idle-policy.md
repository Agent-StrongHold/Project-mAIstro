---
inventory-delta:
  packages/hive-conductor/backend/tests: +12
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

Second repair round: the DAG-run socket authorizes in two phases, and the
activity touch rode inside the same re-resolve as the phase-2 permission
re-check, so a `dags.write` elevation withdrawn between the handshake's
admission check and its touch still slid the idle window (probe reproduction:
 denial with a clock advanced past login refreshed `last_activity_at`).
`_refresh_authenticated_activity` now resolves and authorizes without touching
first and performs the serialized, fail-closed touch only after the full
authorization path — the HTTP middleware's resolve -> authorize -> touch
ordering. Two cases added: `test_revocation_mid_handshake_denies_without_
refreshing_idle_expiry` (denial leaves the idle window and the session
untouched) and `test_accepted_websocket_handshake_is_eligible_activity` (the
positive control: an accepted handshake does refresh).

Third round (independent verification at bdcbe7f2c): the WS ordering fix holds —
a denied handshake, including the mid-handshake `dags.write` revocation, leaves
`last_activity_at` untouched while the accepted-handshake control refreshes.
Every `stores.sessions` mutation path (`_resolve_session`, `_issue_session`,
`revoke_task_elevation`, `logout`, `elevate`, `purge_all_sessions`) takes
`_SESSION_LOCK`, matching the ADR-077 single-writer contract. Re-executed
locally at this head: the focused suite passed 12/12, the full backend suite
passed 2666, `ruff check .` was clean, and the suite-inventory gate matched.
Live rollup on this head reported formal-conformance, exact-debt-ledger, and
the Quality gate SUCCESS; integration-scope, the CI test job, docker-build, the
coverage gate, and gates-ran were still pending at verification time.
