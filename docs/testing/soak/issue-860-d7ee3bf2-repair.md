# Issue #860 — d7ee3bf2 repair checkpoint

## Frozen scope

- Assigned writer worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD `965c6be8b3a93ffc694cade8cae66eda1587aa32`; supplied base
  `d99e598e1084a183d1280fbe9a2c4de8b50b7f2b` resolves locally.
- Process only issue #860 and the explicit vulture CI repair. No GitHub mutations.
- Initial status clean; no salvage patch required. No current job `check-*.log`
  files in the supplied directory at initial inspection.
- Read-only scope: repository instructions, supplied dispatch/prior failure,
  applicable ADRs, existing soak runner/profile/evidence and adjacent tests,
  vulture checker/ledger and CI arguments. Changes limited to this checkpoint
  and genuinely reproduced issue-related defects or reviewed ledger identities.
- Ambiguity: the supplied base comparison includes substantial unrelated history.
  Preserve that history; do not repair or revert unrelated differences.

## Progress

Snapshot captured; prior result and supplied historical check-3.log read.
That log fails schema-fence expectations (24 statements versus 21). Fresh
`uv sync --locked --extra dev` passed. The exact required vulture command
passed: 1,326 reviewed identities / 1,326 findings, zero unclassified and
never-allowlist findings. No ledger edit is justified by the actual scan.
`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
-x -q` passed: 37 passed, 6 skipped. The supplied historical failure does not
reproduce. Skips are not database concurrency evidence. Both validations ran
with a 1,200-second timeout.

Read accepted ADRs 081426-1f7c (physical identity is Attempt), 081626-f383
(canonical store owns execution fences), 082526-b36a (opt-in TTL/renewal/reclaim)
and 073126-c4e1 (immutable RCs through the canonical release process).
Reconciliation: admission deduplication is not physical-work deduplication;
expiry/recovery must use the canonical Attempt/store seams, not a new scheduler.
No selected immutable RC image/package/configuration is supplied by this lane.

Production and adjacent-test review confirms the independent DDL expectation
already includes the three validation audit columns omitted in the historical
failure. The soak runner always rejects its host topology as exact RC evidence,
cancels its unexecuted schedule probe Run, and samples driver rather than
application loop lag. The rate middleware explicitly owns an in-memory limiter
per instance. Adjacent tests exercise the real middleware and document separate
allowances for the same identity on two instances. Focused validation below distinguishes these tests from an actual deployed soak.

## Additional executed validation

All commands used 1,200-second timeouts:

- `uv run pytest tests/test_soak_promotion_gates.py
  tests/test_prod_stack_boot_contract.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  packages/maistro-server/tests/api/test_rate_limit.py -x -q`: **100 passed**.
  Includes real rate middleware, process-group sampling and fail-closed CLI
  tests. This is not a deployed multi-replica experiment.
- `uv run ruff check .`: **PASS**.
- `uv run ruff format --check .`: **PASS**, 3,195 files.
- `uv run python scripts/check-merge-markers.py`: **PASS**.
- `uv run python -` imported the current `scripts/soak/run_soak.py` evaluator
  and checked `evidence/m3a-round30-shakedown.json`. Observed 420.08 seconds;
  failed gates exactly `sustain_duration` and `exact_rc_artifact`. Assertions
  required those failures and the current artifact check's `ok is False`.
  This re-evaluates historical evidence; it is not a new soak.

## Acceptance evidence

| #860 criterion | Executed evidence / unresolved boundary |
| --- | --- |
| Representative release-candidate profile | **UNVERIFIED complete.** Read profile `m3a-load-profile.md:145–164` and runner `scripts/soak/run_soak.py:1372–1395`: one credential, narrow request mix, no representative users/Workspaces, Graph fan-out, successful tool/model, Canvas or Goal/background workload. |
| Two application replicas | **UNVERIFIED deployed RC.** Read `deploy/docker-compose.prod.yml:26–77`; two replica services exist and boot-contract tests passed, but no exact-RC deployment ran. |
| Sustained pool saturation, queue growth, expiry/reclaim, retries, leaks and restart | **UNVERIFIED.** Historical 420.08-second evidence fails the 14,400-second threshold in the current evaluator. Sampler regression tests do not prove sustained application behavior. |
| No duplicate physical work across replicas | **UNVERIFIED.** `scripts/soak/run_soak.py:1044–1072` cancels the schedule probe's unexecuted Run. Admission identity checks cannot prove Attempt execution uniqueness or Goal reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED overall; separate allowances reproduced.** Executed `tests/test_soak_promotion_gates.py:439–493` using production middleware: the same identity gets `[200, 200, 429]` independently on each replica. `packages/maistro-server/src/maistro_server/api/rate_limit.py:32–37` explicitly specifies process-local budgets. Local limiter and retryable-backpressure tests pass; shared-budget acceptance needs explicit reconciliation, not a silent waiver. |
| Complete telemetry with thresholds | **UNVERIFIED.** `scripts/soak/run_soak.py:1410–1424` records driver loop lag, not application loop lag. Profile documents missing worker/saturation/long-window observations. |
| Active-work kill/restart proves drain/fencing/recovery | **UNVERIFIED.** `scripts/soak/run_soak.py:1427–1489` records exit/rejoin and HTTP counters without an observed active-Attempt physical-work oracle. No new restart experiment ran. |
| Long-running exact RC/configuration soak | **BLOCKED / UNVERIFIED.** `scripts/soak/run_soak.py:730–741` deliberately rejects host preflight as exact-RC evidence regardless of duration. No selected immutable RC/configuration was provided; no four-hour run executed. |
| Findings filed/reclassified to earliest broken invariant | **UNVERIFIED completeness.** Existing classifications remain untouched; no new complete load run/classification audit. GitHub mutations prohibited. |
| Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED current RC.** Existing historical artifacts and this validation checkpoint are not an exact-RC evidence pack. |

## Disposition and handoff

**BLOCKED**, not merge-ready. The reported CI defect does not reproduce and the
exact vulture ledger already matches the scan. No speculative source, test or
ledger repair is justified. Only this checkpoint changes; no tests added or
removed, so no inventory delta is required. All inherited work is preserved.
No merge conflict exists; the conditional develop-sync instruction does not
apply. No full-package/full-tree suite or deployed production soak was run.

Next prerequisite: identify the immutable RC image/package/configuration through
the existing release process; complete the representative workload and
application/active-Attempt telemetry, reconcile the rate-budget contract, then
execute at least four hours on that artifact. A repeat of the historical CI
failure or passing unit checks cannot remove these acceptance blockers. This
local documentation commit records diagnosis only, never integration approval.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0,
next: selected RC and missing production acceptance evidence}.
