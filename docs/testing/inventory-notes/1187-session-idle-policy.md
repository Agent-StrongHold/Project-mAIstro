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

Fourth round (post-rejection re-validation at 147d44a89): the third round's
evidence was discarded solely because the provenance commit landed after the
verifier snapshotted bdcbe7f2c ("worktree_changed"), so the entire battery was
re-executed anchored at 147d44a89, where the only delta is this note: ruff
check clean, ruff format clean, focused idle-policy suite 12/12, full backend
suite 2666 passed, suite-inventory gate ok. Code inspection re-confirmed every
acceptance path at this head: the locked min(absolute, idle) resolve in
`routes/auth.py::_resolve_session`, the middleware and WS resolve -> authorize
-> touch ordering (denied `dags.write` handshakes leave `last_activity_at`
untouched; the accepted-handshake control refreshes), observational whoami,
all six locked session mutation paths, and the Profile session-health card
without secrets. Remote CI completion remains the only unverified item.

Fifth round (independent verification at merge head 65d423ed5, the auto-1187
merge of develop 750edd84d): zero production-code delta to the session-policy
files since the fourth-round anchor 147d44a89 (the merge brings only develop's
#1192 pause-waker test, its inventory note, and the CHANGELOG). Re-executed at
this exact head: focused idle-policy suite 12/12, full backend suite 2666
passed, ruff check clean, ruff format clean, suite-inventory gate ok (2666),
ADR-index and ADR-status-language gates ok. Re-derived acceptance: ADR-077
governs 30-minute idle + 7-day absolute server-side expiry; every
`stores.sessions` mutation runs under `_SESSION_LOCK`; HTTP and WS paths both
use resolve -> authorize -> serialized fail-closed touch (denied handshakes and
permission-denied requests leave `last_activity_at` untouched, pinned by
`test_rejected_websocket_handshake_does_not_refresh_idle_expiry` and
`test_revocation_mid_handshake_denies_without_refreshing_idle_expiry`);
`whoami` is observational (restoration cannot slide idle expiry, #1050);
Profile renders the session-health card from `whoami` policy metadata with no
session id. Live rollup on this head: formal-conformance, exact-debt-ledger,
Quality gate, lint-and-type-check, docker-build, and both e2e jobs SUCCESS;
the CI `test` job, coverage publish gate, and `gates-ran` were still pending
at verification time (locally corroborated by the 2666-pass run).

Sixth round (independent verification at 82ea544a5, zero production delta to
the session-policy surfaces since the fifth-round anchor 65d423ed5 — that head
added only this note's fifth-round entry): re-executed from scratch rather
than trusting prior claims. Focused idle-policy suite 12/12; full backend
suite 2666 passed; `ruff check .` and `ruff format --check .` clean;
suite-inventory gate ok (13 suites); ADR-index and ADR-status-language gates
ok; all three exact-debt-ledger steps pass locally (check-ratchet-provenance,
check-shipped-surface-truth, check-vulture-baseline: 1415 reviewed identities
== baseline with no drift). Acceptance re-derived at this exact head: ADR-077
records the governed decision (30-minute sliding idle + seven-day absolute,
server-authoritative); `routes/auth.py::_resolve_session` evaluates
`min(absolute, idle)` inside the shared `_SESSION_LOCK` (also held by
`purge_all_sessions`), pops expired/revoked/deactivated records fail-closed,
and touches only monotonically forward with the absolute cap anchored to
creation; HTTP middleware and both WebSocket routes order resolve ->
authorize -> serialized touch so a denied request or handshake — including a
`dags.write` revocation winning between the handshake's admission check and
its re-check — never slides the idle window; `whoami` is observational, so
#1050 restoration cannot extend authentication (pinned by
`test_whoami_is_observational_and_cannot_keep_an_idle_session_alive`, and
surfaced in Profile's SESSION HEALTH card). Remote CI completion on the PR
rollup remains the only unverifiable item from this environment.

Seventh round (repair-lane re-validation at merge head fd216cb2e, the
auto-1187 merge of develop 60862b6c5): zero production delta to the seven
session-policy surfaces since the sixth-round anchor 82ea544a5 (git diff
--stat shows only this note grew); re-executed from scratch rather than
trusting prior claims. `ruff check .` clean; `ruff format --check .` clean
(2534 files); focused idle-policy suite 12/12; full backend suite 2680
passed (develop's merge added tests; was 2666); suite-inventory gate ok (13
suites); ADR-index and ADR-status-language gates ok; ratchet-provenance and
shipped-surface-truth ok; the CI-contract vulture invocation
(`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) exited 0
with 1415 reviewed identities == 1415 findings. The vulture default scope
remains red on vendored `frontend/node_modules/flatted/python/flatted.py` —
the documented trunk/environmental drift of
`auto-1058-vulture-invocation.md`, not this branch's surfaces. #1050
re-verified at the frontend layer: `AuthGuard` restoration uses the
observational `whoami` call; `WorkspaceContext`'s `ACTIVE_WORKSPACE_KEY` and
`lib/uiState.ts` conveniences are localStorage product state with no authority;
no settings/preferences route can change the module-constant session TTLs.
Remote CI at this exact head was inspected read-only: `test`,
`lint-and-type-check`, both hive-conductor e2e jobs, `docker-build`, postgres
pg17/pg18, `security`, the Quality gate, and coverage (PostgreSQL,
no-services) all SUCCESS; the failures are `Start MinIO`
service-container startup (coverage-MinIO and object-storage jobs, ~33 s
apart), the integration-scope aggregator's evidence-wait for that missing
evidence, and the gates-ran rollup of the same — infrastructure downstream of
one service container; this branch's diff touches no MinIO, workflow, docker,
or compose files versus the develop base.
