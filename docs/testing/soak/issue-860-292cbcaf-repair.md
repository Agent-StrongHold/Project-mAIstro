# Issue #860 — repair checkpoint (292cbcaf)

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting head: `5a673f25cfea52bc719135d0c04786d0a0c6d9b6`.
- Supplied base: `435dc1937e0407ab4de198ffcced49860bb14ad2`.
- Initial worktree clean; no incoming edits to salvage.
- Evidence: supplied dispatch snapshot, prior result `6ed26a6c`, supplied
  failure log `98a11313/check-3.log`. No current-job check logs were present
  in the initial directory listing.
- Review surfaces: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, production rate-limit middleware,
  `packages/maistro-core/tests/persistence/test_pg_learnings.py`, relevant
  ADRs, and the exact vulture gate/ledger. Edit only an evidenced defect on
  those surfaces, any required test inventory note, and this report.
- Assumption: this is the writer repair lane. No release candidate or deployed
  configuration is designated by the assignment; local tests cannot certify
  an exact-RC soak. Prior verification claims must be rerun before reuse.

## Progress

Fresh exact vulture gate passed: 1323 findings / 1323 reviewed identities,
zero unclassified and zero never_allowlist (gate-selected base `4aa68edc0b6b`).
No unbanked identity warrants a ledger amendment.

Fresh focused pytest command passed: 103 passed, 6 skipped in 2.35s:
`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`.
The supplied failure (21 expected schema statements versus 24 observed) did
not reproduce. Skipped tests are not live PostgreSQL evidence.

`uv run ruff check .` passed; `uv run ruff format --check .` passed (3270 files).
Additional checks all exited 0:

- `uv run python scripts/check-deployment-claims.py` (component existence,
  not deployed-behavior proof).
- `uv run python scripts/check-merge-markers.py`.
- `uv run python scripts/check-backlog-consistency.py` (168 items).
- `git diff --check`.

## Architecture and actual failure evidence

Read repository instructions and accepted ADR-081226-69ee, ADR-081626-f383,
ADR-082526-b36a, and ADR-085. Preserve the canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` model, canonical persistence
fences and canonical principal resolution.

**Correction to the prior handoff:** ADR-081626-f383 originally deferred
expiry takeover, but accepted ADR-082526-b36a subsequently defines TTL,
fenced renewal, reclamation and executor heartbeats. Reclaim is therefore
not an undefined architectural contract. #860 must observe the existing
canonical implementation under load, not introduce another reclaim authority
or waive that acceptance criterion. This round did not validate live reclaim.

The supplied `check-3.log` expected 21 DDL statements and observed 24.
`packages/maistro-core/tests/persistence/test_pg_learnings.py:171–175`
already includes the three audit columns missing from that old expectation.
The freshly passing test checks the complete ordered DDL body independently;
production holds the advisory lock inside the transaction before upgrades
(`packages/maistro-core/src/maistro/persistence/pg_learnings.py:215–216`).
No schema/test edit is warranted by that stale failure.

Rate middleware is installed at
`packages/maistro-server/src/maistro_server/main.py:648` and constructs an
`InMemoryRateLimiter` at `api/rate_limit.py:93`. The executed regression
`tests/test_soak_promotion_gates.py:439` tests the production middleware with
the same identity on two instances: each independently returns 200,200,429,
for both authenticated and unauthenticated cases. This is not a deployed
cluster soak, but it falsifies an assumption of shared principal allowance.
Existing #842 process-local semantics do not satisfy #860's stronger
replica-selection non-bypass requirement. Do not add a competing security
path to paper over it.

## Acceptance review

| Criterion from supplied issue snapshot | Executed evidence / disposition |
| --- | --- |
| Representative RC workload | UNVERIFIED. `docs/testing/soak/m3a-load-profile.md:151–170` explicitly lacks users/Workspaces, fan-out, successful tool/model calls, Design/Canvas and background-worker workloads. |
| At least two deployed application replicas | UNVERIFIED for RC. Focused tests use two middleware instances, not the promoted deployment. |
| Sustained saturation, queue growth, reclaim, retry/backoff, leaks and shutdown | UNVERIFIED. No long-running load was executed; local regressions do not establish these observations. Reclaim has an accepted canonical contract as corrected above. |
| No duplicate physical work across schedules/task/Run/Attempt/Goal reconciliation | UNVERIFIED. The profile at lines 193–203 admits its occurrence probe cancels the Run without executing it; admission identity is not physical-work uniqueness. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT PROVEN. Independent allowances reproduced by production-middleware tests above; successful backpressure tests are not distributed-security proof. |
| Required PostgreSQL/application/worker telemetry and pass/fail thresholds | UNVERIFIED. No new RC telemetry. The profile acknowledges driver-loop lag is not application-loop lag and worker/leak observations remain incomplete. |
| Kill/restart during active work proves drain/fencing/recovery | UNVERIFIED. No deployed active-work fault injection; exit/rejoin alone cannot prove physical recovery. |
| Long-running exact-RC artifact/configuration soak; rerun after changes | BLOCKED / UNVERIFIED. No immutable RC artifact and complete runtime configuration designated. `scripts/soak/run_soak.py:730` always rejects host-process preflight artifact certification; executed tests protect that distinction even at four-hour duration. |
| Findings filed/reclassified before promotion | UNVERIFIED externally. Findings recorded locally here; no GitHub mutations permitted or performed. |
| Machine/human evidence tied to image/package/commit/config hashes | UNVERIFIED for RC. This source-checkout report does not bind a promoted deployment. |

## Handoff

**BLOCKED.** No reproduced CI defect or unbanked vulture finding warrants a
code/ledger change. Only this report changed; no tests added, so no inventory
delta is required. No gates, grants, ledger, production code or historical
work were altered. No push, merge or GitHub mutation.

Required next inputs/work: immutable RC artifact/configuration designation;
representative workload and missing telemetry; resolution of replica-selection
semantics through canonical security; an actual long-running exact-artifact
soak with active-work recovery and physical-work observation. Designation is
UNRESOLVED, not permission to promote a substitute preflight. Repeating the
same stale schema failure or clean vulture scan cannot resolve those blockers.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "designate RC and complete production-soak prerequisites"}`.
This bounded attempt is checkpointed by the local report commit, not an
integration approval.
