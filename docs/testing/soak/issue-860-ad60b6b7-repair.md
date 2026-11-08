# Issue #860 — repair checkpoint ad60b6b7

## Frozen scope

- Issue #860 only; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting head verified: `ecd1d8e44f856627e42ba91e503adb9a21423122`.
- Supplied comparison base: `2154f845347c9541016288c760f8da3f5cd2e064`.
- Initial worktree clean; no uncommitted salvage required.
- Inputs: supplied dispatch-context.json, prior result dca78d00, prior logs
  98a11313/check-{0,1,2,3}.log. No check logs present in current job directory.
- Inspect repository instructions, relevant ADRs, `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, soak load profile/evidence, and
  vulture gate/configuration. Only amend `quality/vulture-baseline.json` if
  fresh scanner evidence identifies reviewed retained identities. This note
  records results; production/test changes require concrete observed evidence.
- No remote mutations, branch synchronization, gate weakening, or unrelated
  changes. The large inherited comparison diff is not this repair's edit scope.

## Validation results

Prior artifact reports BLOCKED, not acceptance. Fresh exact vulture scan passed:
1323 reviewed identities / 1323 findings; zero unclassified or never-allowlisted
findings. No evidence justifies changing the ledger. The supplied failed
check-3.log instead reports 24 learning-schema DDL statements versus 21
expected; independently reproducing that test is the next check. Full issue
acceptance body read from the frozen dispatch snapshot.
Fresh focused validation: 117 passed / 6 skipped for learning schema, soak
promotion gates and production boot contract; 27 passed for server rate limit
and task concurrency backpressure tests. Whole-tree ruff lint and format checks
passed (3277 formatted files). The reported historical schema failure does not
reproduce: current test independently expects all three Gauntlet audit columns.
No new tests or production edits are justified by that already-fixed failure.

Accepted ADR-081226-a66b and ADR-081626-f383 retain canonical Run/NodeRun/Attempt
ownership and explicitly do not authorize implicit lease-expiry takeover.
ADR-085 requires per-principal request limiting. Issue #860's reclaim criterion
cannot authorize introducing a competing recovery authority. The load profile
explicitly identifies missing representative classes and exact-RC topology.

Ambiguity: dispatch describes both verifier and writer roles; explicit lane is
repair and requires a local commit, so proceeding as writer.

## Executed commands

Validation timeout: 1200 seconds per invocation.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323/1323 identities.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`: PASS, 117 passed, 6 skipped. Skips are not live database validation.
- `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: PASS, 27 passed.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3277 files already formatted.
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.
- `uv run python scripts/check-adr-index.py`: PASS.
- `uv run python` with `runpy.run_path('scripts/soak/run_soak.py')`: PASS assertions that `preflight_artifact_check()['ok']` is false and historical `docs/testing/soak/evidence/m3a-round6-shakedown.json` fails both `sustain_duration` and `exact_rc_artifact`.

Prior check-0/1/2 logs were read: dependency setup, lint and format succeeded.
Prior check-3 failed the learning-schema test; this round's executed test passes.
No current-job driver logs were supplied. No new soak was executed.

## Acceptance audit against current behavior

| Criterion | Evidence / disposition |
| --- | --- |
| Representative RC workload profile | `m3a-load-profile.md` explicitly lists missing concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background workers. Complete profile UNVERIFIED. |
| At least two deployed application replicas | ASGI tests exercise two real middleware instances, not deployed RC replicas. UNVERIFIED. |
| Sustained saturation, queues, reclaim, retries and leaks | No new sustained load. Historical artifact freshly rejected for duration and identity. UNVERIFIED. |
| No duplicated physical work, including Goal reconciliation | `scripts/soak/run_soak.py:1067` cancels schedule-probe Runs without executing them. Admission-only testing cannot prove physical uniqueness. UNVERIFIED. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | `tests/test_soak_promotion_gates.py:439` freshly passes by observing [200, 200, 429] independently on both replicas for the same authenticated or unauthenticated identity. Production `main.py:648` installs the middleware; `api/rate_limit.py:93` allocates its process-local limiter. Aggregate non-bypass NOT MET; full deployed security/degraded behavior UNVERIFIED. |
| Complete telemetry and explicit thresholds | Profile documents partial measurements; driver-loop latency is not application-loop latency. Fresh RC telemetry UNVERIFIED. |
| Restart during active work; drain/fencing/recovery | Unit gate tests and process rejoin cannot demonstrate physical recovery. No active-work RC restart performed. UNVERIFIED. |
| Long soak of exact RC artifact/configuration | `run_soak.py:744` rejects the host-process topology by construction. Exact production image/config soak for >=4 hours UNVERIFIED. |
| Findings classified to earliest broken invariant | Backlog consistency passes; completeness of production findings/classification UNVERIFIED. No GitHub mutation. |
| Machine/human evidence tied to exact hashes | This report is local validation, not a hash-bound production soak. UNVERIFIED. |

## Handoff

**BLOCKED**, not merge-ready. Supplied CI failure is already fixed and the
vulture ledger matches the current scan. Neither warrants speculative code,
test, or ledger edits. This report is the sole changed file; no test inventory
delta is needed because no tests changed.

Remaining prerequisites: select an immutable RC image/configuration manifest and
representative supported workload; resolve process-local versus aggregate
non-bypass policy; measure physical effects and recovery through the canonical
execution spine; execute the >=4-hour exact-RC soak and publish hash-bound
telemetry. Accepted fencing ADR does not permit implicit takeover as a shortcut.
No new scheduler, execution authority, Goal store, event authority or auth path
was introduced. Inherited branch/base divergence was not altered or certified.

Progress: checked 1 issue; acceptance-complete 0; skipped 0; failed commands 0;
blocked 1. Next: production acceptance work, not another speculative CI repair.
