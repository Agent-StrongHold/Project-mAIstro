# Issue #860 repair checkpoint

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD `76f8b9c8c044464b7a8da4fb6a6e81df58e2d220`, develop base `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Worktree was clean on entry; no salvage patch needed.
- Process the supplied dispatch snapshot and prior result, not live GitHub lists.
- Inspect existing #860 changes/tests, relevant ADRs, supplied failure log, and vulture gate. Edit only evidence-supported repairs, the explicitly authorized vulture ledger, test inventory notes if tests change, and this report.
- Current-job directory has no `check-*.log` files. Prior result reports BLOCKED and expressly does not establish exact-RC production soak acceptance.
- Assumption: this is a writer CI-repair round, not authorization to alter production execution architecture or manufacture soak evidence. Exact edit targets beyond this report will be recorded after gate evidence.

## Progress

- Confirmed assigned worktree and exact starting HEAD; clean status.
- Read prior result `47d55b89fb8d451ba14e7fd605be5cad/result.json`: production acceptance remains UNVERIFIED; independent replica allowances and peer receipt 404 were reproduced previously, not yet independently checked in this round.
- Read the supplied prior failing log: ordered schema assertion expected 21 DDL statements but observed 24. Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: **37 passed, 6 skipped**. The reported failure does not reproduce.
- Required exact vulture command passed: **1322 findings / 1322 reviewed identities, zero unclassified**, selected trusted base `321cbdb8fe9b`. There are no unbanked identities to repair; do not amend the ledger without evidence.
- Read issue #860's full acceptance body and PR #1672 body from the frozen dispatch. No exact RC artifact/configuration is specified there. The prior report identifies the same missing production evidence; rerunning passing CI is not sufficient acceptance.
- Final edit scope: this report only; fresh focused validation found no repairable CI failure. Read-only validation targets: `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, `packages/maistro-core/{src/maistro/persistence/pg_learnings.py,tests/persistence/test_pg_learnings.py}`, `packages/maistro-server/{src/maistro_server/api/{rate_limit,tasks}.py,tests/api/test_tasks_concurrency_backpressure.py}`, existing load profile, ADRs and relevant workflow.

## Fresh validation results

All commands ran inside the assigned worktree, with up to 1200 seconds per validation invocation:

| Command | Outcome |
|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Passed: 1322 reviewed identities match 1322 findings |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; no live PostgreSQL proof from skipped tests |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 73 passed |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed: 3301 files formatted |
| `uv run python scripts/check-ratchet-provenance.py` | Passed; 53 quality JSON consumers have explicit provenance |
| `uv run python scripts/check-shipped-surface-truth.py` | Passed |

The gate commands match `.github/workflows/vulture-ratchet.yml`. No ledger or authorization edits are warranted. Provenance emitted existing invalid-escape SyntaxWarnings, not failures. No tests were added or changed, so there is no inventory delta.

## Architecture and reachable behavior

Read accepted ADR-081226-69ee, ADR-081626-f383 and ADR-082526-b36a. The later lease ADR adds renewal/reclaim to the earlier fencing contract; lack of soak evidence must not be misreported as lack of a lease mechanism. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; no execution, scheduling, event, store or authorization authority changed.

- `packages/maistro-core/src/maistro/persistence/pg_learnings.py:215` wraps schema upgrades in one transaction and takes the advisory lock first. The independent ordered test at `packages/maistro-core/tests/persistence/test_pg_learnings.py:173` already includes the three validation-audit columns absent in the supplied old failure log.
- `packages/maistro-server/src/maistro_server/api/rate_limit.py:93` constructs a process-local limiter. Executed `tests/test_soak_promotion_gates.py:439` uses the production middleware and observes `[200, 200, 429]` independently on both instances for the same identity. This agrees with the documented N-times-limit semantics; it does not establish the issue's stronger replica-selection acceptance or justify inventing a new authorization path.
- `packages/maistro-server/src/maistro_server/api/tasks.py:144` reads receipts from the injected queue. Executed `tests/test_soak_promotion_gates.py:564` uses the production router and canonical admission spine, observing owner 200 and peer 404. These are component probes, not a deployed topology.
- `scripts/soak/run_soak.py:744` explicitly returns `exact_rc_artifact.ok=false`. Executed promotion tests verify that even synthetic four-hour evidence cannot bypass that requirement. Removing the gate would falsify evidence rather than repair the issue.

## Acceptance disposition

| Issue #860 acceptance | This round's evidence |
|---|---|
| Representative users/Workspaces, request mix, fan-out, schedules, tools/models, Design/Canvas and background workers | **UNVERIFIED**. Read `docs/testing/soak/m3a-load-profile.md` completely; its remaining-gaps section expressly identifies these missing workloads. |
| At least two supported production application replicas | **UNVERIFIED**. Two-instance ASGI component probes passed, not a production deployment. |
| Sustained saturation, queue growth, lease reclaim, retries, memory/descriptor/process leaks and restart | **UNVERIFIED**. Short tests cannot demonstrate sustained behavior. |
| No duplicate physical work across schedule/Run/Attempt admission and Goal reconciliation | **UNVERIFIED**. Admission tests are not physical-work proof; the documented schedule probe cancels its queued Run. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED** for production; independent per-replica allowances reproduced through production middleware. No deployed ingress policy was tested. |
| PostgreSQL connections/query latency/locks, application-loop latency, workers/RSS/fds/queues/errors with thresholds | **UNVERIFIED**. Sampler tests passed, but no fresh production telemetry; driver-loop latency is not application-loop latency. |
| Kill/restart during active work, drain/fencing/recovery | **UNVERIFIED**. No active physical Attempt failure injection performed. |
| Long soak of exact RC artifact/configuration, rerun after changes | **UNVERIFIED / BLOCKED**. Current runner is explicitly a host-process preflight; no immutable RC artifact/configuration was supplied for execution. |
| Findings filed/reclassified to earliest broken invariant | **UNVERIFIED** for completeness. Existing findings retained; no GitHub mutation performed. |
| Publish machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED**. This validation report is source-bound component evidence, not a production-soak evidence pack. |

## Handoff

**BLOCKED** on production acceptance, not on the cited CI failure. Changed file: this report only. No speculative product fixes, ledger churn, weakened gates or discarded prior work. Local commit records the completed validation item, not integration approval.

Required next input/work: select immutable RC images and normalized supported runtime configuration, complete the representative workload, then run the profile's >=4-hour production soak with application telemetry and active Attempt failure/recovery proof. Any code/runtime-config changes require a new soak. Repeating the already-passing vulture/schema checks does not resolve this blocker.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC production soak}`. The single assigned issue was checked; no claim of completed issue acceptance.

