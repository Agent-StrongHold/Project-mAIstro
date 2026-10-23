# Issue #860 — bounded repair 27cec39d

## Frozen scope

- One assigned item: #860; branch `auto-860`, starting HEAD
  `d93009b53aada41d30e2254d88375f390fcebd34`, supplied base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Starting worktree clean. No salvage required.
- Inspect repository instructions, relevant ADRs, existing soak harness/profile,
  adjacent tests, supplied dispatch snapshot and cited validation failure.
- Candidate edits limited to this report and `quality/vulture-baseline.json`
  if the mandated scanner identifies reviewed retained identities. Genuine
  issue-related dead-code repairs require evidence before expanding this list.
- No new issue/PR enumeration, GitHub mutation, deployment promotion, or
  alternate execution/authorization authority.

## Initial evidence and ambiguity

The supplied prior result is BLOCKED, not acceptance evidence. This job directory
contained no `check-*.log` files at entry. The cited historical failure will be
inspected and validation rerun. The assignment is a writer CI-repair round;
ledger amendments are allowed only for actual scanner findings. No exact RC
artifact/configuration was designated in the lane brief; local harness checks
must not be represented as an exact-RC soak.

## Validation and acceptance

- Required vulture command: PASS, 1323 findings / 1323 reviewed identities,
  zero unclassified and never-allowlist findings. No ledger amendment justified.
  Scanner selected provenance base `4aa68edc0b6b`; no baseline was edited.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  PASS, 37 passed, 6 skipped. The cited historical failure was an expected-DDL
  count of 21 versus 24 observed; it does not reproduce on the assigned HEAD.
  Skipped database tests do not prove live multi-replica safety.
- Read accepted Graph/Node, execution lease/fencing, renewal/reclaim and rate
  limiting ADRs. The later renewal/reclaim contract extends the earlier lease
  boundary; no deferral or substitute scheduler is introduced. Per-principal
  rate keying does not itself establish a cluster-wide request allowance.
- Reviewed existing profile and adjacent promotion tests. The profile explicitly
  calls this runner a host-process preflight, missing representative workload
  classes and exact promoted topology. Synthetic four-hour fixtures are not
  four-hour execution evidence.

## Additional executed checks

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  PASS, 66 tests. Includes real production-middleware instances, a real child
  process resource sampler, fail-closed promotion checks, and canonical task
  admission/backpressure wiring. Not deployed RC load evidence.
- `uv run python scripts/check-suite-inventory.py`: PASS, 17 suites,
  31128 unique test identities, no duplicate evidence.
- `git diff --check`: PASS before final report completion.

The historical schema failure is already covered by the three validation audit
columns in `packages/maistro-core/tests/persistence/test_pg_learnings.py:176–178`.
Production `pg_learnings.py:215` takes the transaction before the advisory lock
and all upgrade DDL. No new test or source change is warranted for that failure.

## Acceptance assessment

| #860 criterion | Fresh evidence / remaining gap |
| --- | --- |
| Representative release-candidate profile | UNVERIFIED. `docs/testing/soak/m3a-load-profile.md:155` explicitly identifies missing users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background workloads. RC scope not designated in assignment. |
| At least two deployed application replicas | UNVERIFIED. Executed two production-middleware instances via ASGI, not two deployed RC replicas. |
| Sustained saturation, queues, lease reclaim, retries, memory/descriptor/process leaks | UNVERIFIED. Sampler test observes real child-process growth, but no sustained production observation window was executed. |
| No duplicate physical work across schedules/tasks/Run/Attempt/Goal | UNVERIFIED. Admission evidence tests reject empty/conflict-only probes; this does not witness fenced physical execution across replicas. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | UNVERIFIED at deployment grade; `tests/test_soak_promotion_gates.py:439` reproduces independent 200/200/429 allowances for the same identity on two production limiter instances. `packages/maistro-server/src/maistro_server/api/rate_limit.py:93` creates instance-local state. Backpressure test proves retryable 429 and later readmission, not cluster-wide enforcement. |
| Complete telemetry with explicit thresholds | UNVERIFIED. Profile has thresholds but acknowledges absent application-loop, pool-saturation and worker/reclaim observations. Driver-loop latency cannot substitute for application-loop latency. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED. Promotion-gate and boot-cleanup tests pass; no active RC service was killed or restarted in this round. |
| Long soak of exact RC artifact/configuration | BLOCKED / UNVERIFIED. `scripts/soak/run_soak.py:730` returns `ok: false` for host-process preflight artifact equivalence. Executed synthetic four-hour tests prove rejection, not elapsed soak time. Designated immutable RC/configuration and exact-topology runner are still required. |
| Findings filed/reclassified to earliest broken milestone | Local disposition recorded here; external filing/reclassification UNVERIFIED. No GitHub mutation authorized or performed. Rate-limit allowance concern belongs to the rate-limiting invariant, not a throughput optimization. |
| Machine/human evidence bound to image/package/commit/config hashes | UNVERIFIED for the promoted RC. This report is bound to the assigned source HEAD, but neither it nor historical preflight artifacts certify the current release image/configuration. |

## Disposition and handoff

**BLOCKED**, not integration approval. Only this report changes; source, tests,
ledgers, grants and inventory counts remain untouched. No inventory-delta note
is required because no tests were added or removed. No reproducible CI failure
or unbanked identity exists to repair in this round. Do not manufacture ledger
changes or substitute another preflight run for promotion acceptance.

Required next work: designate the immutable RC/configuration and applicable
workload scope; provide exact-topology execution with complete telemetry and
physical-work witnesses; run a fresh minimum-four-hour soak including active-work
recovery; disposition observed invariant failures before promotion. Existing
accepted execution authorities remain unchanged:
`Goal -> Graph -> Run -> NodeRun -> Attempt`.

Progress: checked 1 issue, done 0 (release acceptance incomplete), skipped 0,
validation errors 0; next: resolve the RC/workload/runner prerequisites above.
Report committed locally for handoff only.
