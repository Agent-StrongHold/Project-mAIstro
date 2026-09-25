---
inventory-delta:
  packages/hive-conductor/backend/tests: +17
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

Eighth round (independent verification at 3ee9f6030): re-executed the lane
checks rather than trusting the seventh-round claims — `ruff check .` clean,
`ruff format --check .` clean, focused idle-policy suite 12/12, full backend
suite 2680 passed, suite-inventory gate ok (2680 recorded), ADR-index,
shipped-surface-truth, and public-routes gates ok; the default-scope vulture
run's single unclassified finding is the gitignored
`frontend/node_modules/flatted` copy already documented above (environmental,
not this branch). Closure hygiene: PR #1471 body says "Refs #1187" only and no
branch commit contains fixes/closes/resolves. NEW FINDING (regression
introduced by this branch, reproduced end-to-end):
`routes/auth.py::_resolve_session` now pops ANY stored record whose
`created_at` is missing/unparseable, and the first-run setup claim sentinel
(`routes/setup.py` `_SETUP_CLAIM_KEY = "__hive_setup_claim__"`, record shape
`{"claimed_at": ...}`) lives in the same `stores.sessions` JsonStore. An
UNAUTHENTICATED `GET /v1/tasks` with `Cookie: hive_session=__hive_setup_claim__`
travels `AuthMiddleware._get_user -> resolve_principal -> get_current_user ->
_resolve_session` and deletes the in-flight one-shot setup claim —
`JsonStore.pop` even deletes the durable record (`services/model_store.py`
`JsonStore.pop` -> `self._persisted.delete`). That releases the
`put_if_absent` lock `routes/setup.py` relies on so two concurrent first-user
attempts produce exactly one owner, re-admitting a second
`/v1/setup/complete` during the provisioning window (repro: claim present
before, 401 to the attacker, `_is_setup_complete()` False after; base
develop 60862b6c5 returned None for the same record WITHOUT popping). No test
covers the auth-path/setup-claim interaction. Fix direction: pop only records
with a parseable `created_at` (true expired sessions), or move the setup
sentinel out of the session store. Verdict this round: NEEDS-REPAIR on that
finding; all #1187 acceptance criteria themselves remain demonstrated.

Ninth round (repair at this head): the eighth-round finding is fixed at the
resolution boundary, where the defect lived. `routes/auth.py` gains
`_is_session_record` (a `TypeGuard` recognizing the session shape: string
`created_at` AND non-empty string `user_id` — neither setup marker has either,
the config marker carries `completed_at`), and `_resolve_session` now fails
closed WITHOUT deleting records that do not resolve as sessions; eviction is
reserved for genuine session records (expired, deactivated, corrupt-created-at
sessions are still popped, so the cleanup branch stays reachable for real
sessions). Defense-in-depth at the second mutation path: `logout` pops only
records that resolved as live sessions — over HTTP the middleware already
refuses unresolvable cookies with 401 before the route runs, but the route's
raw-cookie pop was directly reachable by non-HTTP callers. `purge_all_sessions`
(pre-existing at base, operator-only remediation) still clears the whole store
and is left untouched. Five cases added to `test_session_idle_policy.py`:
`test_resolution_denies_but_never_deletes_non_session_records` (both markers
survive resolution; `put_if_absent` still refuses a rival claim),
`test_forged_marker_cookie_through_the_middleware_releases_nothing` (the
eighth-round repro end-to-end: 401 to the attacker, claim intact,
`_is_setup_complete()` True), `test_logout_cannot_delete_the_setup_claim_marker`
(401 over HTTP AND direct route invocation cannot delete the marker),
`test_logout_still_invalidates_a_live_session` (control: real logout works),
and `test_corrupt_session_records_are_still_evicted` (control: the eviction
branch stays reachable for session-shaped records). Re-executed at this head:
focused idle-policy suite 17/17; full backend suite 2685 passed; `ruff check .`
clean; `ruff format --check .` clean; suite-inventory gate ok with this note's
delta (+17, 2685 collected).

Tenth round (independent verification at 27f4fa266): re-executed the lane
checks from scratch rather than trusting prior rounds — `ruff check .` clean,
`ruff format --check .` clean (2534 files), focused idle-policy suite 17/17,
full backend suite 2685 passed, suite-inventory gate ok (2685 recorded),
check-adr-index and check-adr-status-language ok. Re-derived acceptance at
this exact head: ADR-077 records the governed 30-minute idle + seven-day
absolute decision; `_resolve_session` evaluates `min(absolute, idle)` inside
`_SESSION_LOCK` with monotonic refresh and creation-anchored absolute cap;
HTTP middleware and both WS routes order resolve -> authorize -> serialized
fail-closed touch; `whoami` and `request_log` are observational; the only
`get_current_user` callers are the middleware and request log (verified by
grep — no other touch path exists); every `stores.sessions` mutation path is
lock-covered. The eighth-round setup-claim exploit stays fixed and pinned by
its three protection tests plus controls, all passing in this round's run.
Closure hygiene re-checked: PR #1471 body says "Refs #1187" only; no branch
commit contains a fixes/closes/resolves keyword with an issue reference.
Verified `git diff` vs develop base 60862b6c5 touches no workflow, compose,
docker, or MinIO file, so the recorded CI failures (MinIO service-container
startup, the integration-scope aggregator's evidence wait on it, and the
gates-ran rollup) remain infrastructure downstream of a service container,
not this branch's surfaces. Remote CI completion on the PR rollup remains the
only unverified item from this environment.

Eleventh round (independent verification at 992019302, zero production delta
since the tenth-round anchor 27f4fa266 — `git diff --stat` shows only this
note grew). Re-executed from scratch rather than trusting prior rounds:
`ruff check .` clean; `ruff format --check .` clean (2534 files); focused
idle-policy suite 17/17; full backend suite 2685 passed; suite-inventory gate
ok (13 suites); check-adr-index and check-adr-status-language ok. Re-derived
acceptance at this exact head: ADR-077 records the governed decision
(30-minute sliding idle + seven-day absolute, server-authoritative);
`_resolve_session` evaluates `min(absolute, idle)` under `_SESSION_LOCK`,
pops expired/revoked/deactivated session-shaped records, never deletes
non-session store records, and refreshes only monotonically with the absolute
cap anchored to creation; the HTTP middleware touches only after
authentication AND authorization pass, the WS routes order resolve ->
authorize -> serialized fail-closed touch, and `whoami` is observational
(grep confirmed the only `refresh_activity=True` paths are the middleware's
post-authorization `refresh_session_activity` and the WS post-authorization
resolve; every other `get_current_user` caller uses the non-refreshing
default). #1050 re-verified: `AuthGuard` restoration uses the observational
whoami call (pinned by
`test_whoami_is_observational_and_cannot_keep_an_idle_session_alive`); the
session TTLs are module constants with no settings/preference route able to
write them; `lib/uiState.ts` localStorage conveniences carry no authority.
The stop condition holds: idle expiry is enforced in `routes/auth.py` +
middleware + `routes/ws.py`, not frontend storage/navigation. CI-infra
attribution re-checked at this head: zero workflow/compose/docker/MinIO delta
vs 60862b6c5, so the prior MinIO service-container startup failures and their
gates-ran rollup remain environmental. Remote CI completion on the PR rollup
remains the only unverified item from this environment.

Twelfth round (independent verification at merge head af6af1293, the auto-1187
merge of develop 03c8ba83 — the exact PR head). Zero production delta to the
seven session-policy surfaces since the eleventh-round anchor 992019302
(`git diff 992019302 af6af1293` on middleware/auth.py, routes/auth.py,
routes/ws.py, stores.py, test_session_idle_policy.py, Profile.tsx, ADR-077 is
empty); the merge brings only develop's own changes (#1582 chat
session-message retention, #1037, #1560, #1570, #1573, #1554, workflow/compose
edits — develop's "sessions" there are chat session_turns/message stores, not
the `hive_session` auth store) and zero workflow/compose delta vs the develop
base (`git diff 03c8ba83 af6af1293 -- .github/workflows docker-compose.yml` is
empty). Re-executed from scratch rather than trusting prior rounds: focused
idle-policy suite 17/17; full backend suite 2733 passed / 5 skipped (2738
collected, matching the recorded inventory); `ruff check .` clean;
`ruff format --check .` clean (2543 files); suite-inventory gate ok (2738);
check-adr-index OK and check-adr-status-language ok. Acceptance re-derived at
this exact head and unchanged from the eleventh-round derivation: governed
30-minute idle + seven-day absolute server-side expiry (ADR-077);
`_resolve_session` evaluates `min(absolute, idle)` under `_SESSION_LOCK` with
monotonic refresh, creation-anchored absolute cap, and deactivation-as-
revocation; HTTP middleware and both WS routes order resolve -> authorize ->
serialized fail-closed touch (grep: `refresh_activity=True` exists only in the
middleware's post-authorization `refresh_session_activity` and the WS
post-authorization resolve; request_log, oauth-link, whoami, and actor lookups
all use the observational default); whoami observational so #1050 restoration
cannot slide expiry; session TTLs are module constants no settings route can
write; Profile SESSION HEALTH card renders whoami policy metadata with no
session id. Elevation still requires the bounded password re-auth on
`/v1/auth/elevate`. The eighth-round setup-claim finding stays fixed and
pinned (five protection/control tests pass in this round's run). One scope
nuance recorded: the conductor backend has no dedicated HTTP deactivation
route yet (identity/account management is the related #291 surface); the
server-side enforcement contract for `is_active=False` or user deletion —
session popped at the next resolve, `user_has_permission` fails closed — is
implemented and tested end-to-end. Live PR rollup read read-only at this
exact head: lint-and-type-check, both postgres jobs, both e2e jobs, security
(SAST, pip-audit), formal-conformance, exact-debt-ledger, Quality gate,
coverage (no services / PostgreSQL / MinIO), object storage (MinIO),
workflow-lint, pr-base, Gate C, DevSkim all SUCCESS (the MinIO jobs that
failed at fd216cb2e now pass, confirming the infra attribution); still
IN_PROGRESS/PENDING at verification time: CI `test` (locally corroborated by
the 2733-pass run), integration-scope, Coverage gate, docker-build, and the
gates-ran rollup — remote CI completion remains the only unverified item.
Closure hygiene re-checked on the live body and all commit subjects:
"Refs #1187" only; no fixes/closes/resolves anywhere.
