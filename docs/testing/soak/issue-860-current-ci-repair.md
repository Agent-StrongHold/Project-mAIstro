# Issue #860 — current CI repair

## Latest checkpoint — job `cdbeb34bb1d745d28f39fedf9c3bb57b`

Frozen scope: issue #860 only, assigned branch/worktree `auto-860`, clean
starting HEAD `278a8a53763fcd5dd7a76a69133ca69cf16525e8`; assigned base
`c0441cf94b9a8e58517da0f4159070b97ea6a706` verified locally. No conflicts or
uncommitted salvage were present. Prior job `30440cfa` result inspected;
no driver `check-*.log` files existed in the supplied job-directory snapshot.
Candidate edit is this checkpoint only unless fresh validation exposes a real
repair. No immutable RC image/configuration was designated in the assignment;
assumption: a host preflight cannot substitute for the required production soak.

Fresh commands, not inherited verification (1000/1200-second timeouts):

- Exact requested Vulture command: PASS, 1345 findings / 1345 reviewed identities,
  zero unclassified or never-allowlist. Actual comparison base `1e4933e2a1b7`.
  No unbanked identities exist; no ledger amendment or dead-code removal is justified.
- `uv sync --locked --extra dev`: PASS.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2859 files.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`:
  **88 passed, 5 skipped** (no `MAISTRO_TEST_PG_DSN`). No live PostgreSQL proof.

Architecture reviewed: accepted ADR-085 defines principal-keyed rate limiting,
not shared state; ADR-081626-f383 defines canonical durable Attempt fences;
ADR-082426-82c7 defines occurrence-keyed Run admission, not physical-effect
uniqueness. ADR-081 is Proposed. Preserve Goal → Graph → Run → NodeRun → Attempt;
no scheduler, execution, event, store or authorization authority changes.

The prior shared-store H3 claim is already corrected in `m3a-soak-evidence.md`.
Production `RateLimitMiddleware` still constructs independent in-memory limits;
the executed middleware regression demonstrates another allowance on replica 2.
The load profile explicitly records missing users/Workspaces, Graph fan-out,
successful model/tool, Design/Canvas and Goal/background workloads. These are
real remaining acceptance gaps, not Vulture debt or merge conflicts.

Additional fresh validation (1200-second timeout):

- `uv run python scripts/check-suite-inventory.py`: PASS, all 14 suites.
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-compose-secrets.py`: PASS, 8 Compose files.
- `uv run python scripts/check-merge-markers.py`: PASS.
- `git diff --check`: PASS.
- Inline `uv run python` imported the current driver and evaluated the fixed four
  historical packs: `m3a-soak-evidence.json`, `m3a-repair-validation.json`,
  `m3a-round5-final.json`, `m3a-round6-shakedown.json`. Assertions that each fails
  both `sustain_duration` and `exact_rc_artifact` passed. Run 5/6 record 90.17 /
  90.43 seconds, not 14400. This is not a new soak.

Command outputs are in this job's tool transcript; initial Vulture output is
also `/tmp/860-vulture.log`. Inspected reachable middleware installation at
`packages/maistro-server/src/maistro_server/main.py:593`, constructor at
`api/rate_limit.py:72`, real middleware tests at
`tests/test_soak_promotion_gates.py:435`, and production Compose's two-server
reference build/external model-gateway contract. No exact-RC deployment ran.

### Acceptance disposition for this checkpoint

| Criterion | Executed evidence or remaining gap |
|---|---|
| Representative profile | PARTIAL: inspected documented request mix and gaps; RC users/Workspaces and applicable execution/product surfaces UNVERIFIED. |
| Two application replicas | Boot-contract tests pass; two deployed exact-RC replicas UNVERIFIED. |
| Sustained saturation/reclaim/retry/leaks | UNVERIFIED; no sustained run performed. |
| No duplicate physical work / Goal reconciliation | UNVERIFIED; occurrence admission is not physical execution or recovery proof. |
| Rate/security/degraded non-bypass | Independent replica allowance reproduced by production-middleware tests; aggregate non-bypass unmet. Full RC security/degraded behavior UNVERIFIED. |
| Complete telemetry and thresholds | Sampler regression passes; application-loop/worker/RC telemetry coverage UNVERIFIED. |
| Active-work kill/restart and recovery | UNVERIFIED; no live replica restart performed. |
| Long-running exact-RC soak | All four historical packs fail duration and artifact gates; qualifying run UNVERIFIED. |
| Findings classified/filed | Local F11/F12 M3-A classifications inspected; external filing UNVERIFIED and prohibited in this lane. |
| Hash-bound machine/human evidence | Historical packs evaluated; qualifying RC evidence UNVERIFIED. |

**BLOCKED**: no evidenced CI ledger failure or sync conflict to repair. No source,
config, ledger, grant, tests or raw evidence changed; no inventory delta needed.
Only this checkpoint is committed. No GitHub mutations or integration approval.
Next: designate the immutable RC image/configuration, complete production-profile
workloads and telemetry/physical-effect oracles, resolve the replica-budget
contract mismatch, then run ≥14400 seconds on that unchanged artifact. Another
host preflight or speculative ledger amendment cannot satisfy the acceptance.
Progress: checked 1 issue, done 0 acceptance-complete, skipped 0 issues,
errors 0 validation commands; 5 database tests skipped.

---

## Historical checkpoint — job `8c939288e0f948ee8ecd7c21abb76db9`

Only #860, writer CI-repair, assigned worktree `/home/dev/Git/wt/auto-860`.
Verified clean starting HEAD `cffdf7caf4427ed2f5c4737c371f162364890280`;
assigned base `b35c76e035b3ee60789f9eac3e82526e23aba2e1` resolves.
No conflict or salvage edits were present. Prior `c99b4bd1` result read;
no driver `check-*.log` files were present in the job-directory snapshot.

Fresh validation (1200-second timeouts except initial Vulture scan: 1000):

- `uv sync --locked --extra dev`: PASS.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, **1345 findings / 1345 reviewed identities**, zero unclassified or never-allowlist. The checker reports comparison base `1e4933e2a1b7`. No actual debt mismatch exists, so **no ledger amendment or code deletion is justified**.
- `uv run ruff check .`: PASS; `uv run ruff format --check .`: PASS, 2859 files.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`: **88 passed, 5 skipped** (missing `MAISTRO_TEST_PG_DSN`). No live PostgreSQL proof claimed.
- `uv run python scripts/check-suite-inventory.py`: PASS, 14 suites.
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-compose-secrets.py`: PASS, 8 Compose files.
- `uv run python scripts/check-merge-markers.py`: PASS.
- Inline `uv run python` imported the current runner and asserted that all four historical packs in the table below fail both duration and exact-artifact checks: PASS. Run 6 remains 90.43 seconds versus 14400 required. This is evidence evaluation, **not a fresh soak**.

Fresh transcripts are `worker-ruff-{check,format}.log`, `worker-pytest.log`,
`worker-check-*.py.log` and `worker-evidence.log` in the supplied job directory.
Initial Vulture output is in the tool transcript (also `/tmp/pi-bash-96319284b9bf785c.log`).

Re-read repository instructions, the load profile, evidence pack, current runner,
adjacent tests and production limiter. Accepted ADR-085 defines principal keys,
not shared replica state; accepted ADR-081626-f383 and ADR-082526-b36a require
canonical fencing and lease renewal/reclaim. Accepted ADR-082426-82c7 makes the
occurrence the Run admission identity, not proof of physical effects. ADR-081
remains Proposed. No alternative execution or authorization authority introduced.

The acceptance table below remains **BLOCKED**. Executed production-middleware
regressions reproduce independent allowances on both replicas for authenticated
and pre-auth identities (`rate_limit.py:25-30,72`; middleware installed in
`maistro_server/main.py:593`). The old shared-store claim is already corrected.
`run_soak.py:635-646` explicitly rejects host-preflight artifact equivalence;
no designated immutable RC image/configuration/provider manifest was supplied.
No live RC replicas, sustained workload or active-work restart ran this round.
Full profile, physical-work uniqueness, application telemetry, recovery, external
finding filing and hash-bound promotion evidence therefore remain UNVERIFIED,
not inferred from passing unit tests.

Only this checkpoint changes. No tests added, so no inventory delta is needed;
no code/runtime configuration, ledger, grants or historical evidence changed.
Commit locally; no GitHub mutations. Next: release-owner designation of the exact
RC, completion of production workload/telemetry and physical-effect oracles,
resolution of the replica-budget mismatch at the canonical policy seam, then
≥14400 seconds on that unchanged artifact/configuration. Another host preflight
or speculative ledger edit cannot resolve the block.

Progress: checked 1 issue, done 0 acceptance-complete, skipped 0 issues,
errors 0 validation commands; 5 database tests skipped. CI debt failure did not
reproduce; issue #860 remains unresolved.

---

## Historical checkpoint — job `9ca96a35080a4b3f8c7ea6d01dc083aa`

Frozen item: #860 only, branch `auto-860`, verified clean starting HEAD
`62b69b3f500e40fa65e2ab91663e10083d3a544b`. Assigned develop base remains
`cf4a562b65e0f459eec8e77e8b10ca7aa4f847d0`; the vulture gate uses the actual
merge base `045cfdfbe3ea`. No merge conflict exists. Previous result
`617c8e0536a54be8b6a065a42827903e/result.json` was inspected, not accepted as
fresh verification. No driver `check-*.log` files were supplied in this job.

Freshly executed (logs in the supplied job directory):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: exit 0; 1,360 reviewed identities match 1,360 findings, zero unclassified/never-allowlist (`worker-vulture.log`). No ledger amendment or dead-code deletion is justified.
- `uv run ruff check .` and `uv run ruff format --check .`: both exit 0 (`worker-ruff-check.log`, `worker-ruff-format.log`).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q -rs`: **80 passed, 5 skipped** (`worker-pytest.log`). All five skips require a migrated database via `MAISTRO_TEST_PG_DSN`; this is not live PostgreSQL evidence. Includes real production-middleware replica-selection counterexamples, real task router/spine backpressure, and the live Linux child-process sampler regression.

Additional fresh checks: `uv run python scripts/check-deployment-claims.py`,
`uv run python scripts/check-execution-lifecycles.py`,
`uv run python scripts/check-merge-markers.py` and `git diff --check` all passed.
The current `failed_promotion_checks` evaluator rejected each of the four fixed
historical packs listed below for both duration and exact artifact; assertions
passed (`worker-evidence-check.json`). Run 6 still records only 90.43 seconds.
This evaluates historical evidence, not a new soak or its passing flags' validity.
Production `maistro_server/main.py:588` installs the inspected limiter.

Re-inspected production `RateLimitMiddleware` and reference Compose, the
current artifact gate, tests and load/evidence profile. The old H3 shared-store
claim is already corrected. The passing middleware regressions still demonstrate
independent replica allowances, **not** non-bypass of an aggregate principal
budget. The reference Compose declares two servers but supplies a local image
build and mutable dependency tags; the assignment does not designate an immutable
RC image/configuration. A four-hour host-process run would still fail the explicit
`exact_rc_artifact` gate and would not resolve this block.

Architecture reconciliation: accepted ADR-081226-69ee retains Graph → Run →
NodeRun → Attempt; ADR-082126-f69c makes schedules canonical Run producers, not
a second runtime. Accepted ADR-081626-f383 distinguishes durable stale-writer
fencing from lease-expiry takeover. Therefore admission counts, process rejoin and
terminal Run counts do not certify physical-work uniqueness/reclaim. ADR-081 is
Proposed, not an accepted waiver. No execution or authorization authority changes.

The ten-criterion acceptance disposition below remains **BLOCKED**. No new
production soak, multi-replica deployment, active-work restart, or external finding
filing is claimed. No code, runtime configuration, tests, inventory counts, ledgers,
grants or historical evidence changed; this checkpoint is the only tree edit.
The required next work remains designation of the exact RC/configuration, a
representative production workload and telemetry/recovery oracle, resolution of
the replica-limit mismatch, and a qualifying ≥14,400-second unchanged-artifact run.

Progress: checked 1, done 0, skipped 0 issues, errors 0 validation commands;
5 database tests skipped. Commit this checkpoint; #860 remains unresolved.

---

The following sections preserve the previous job's checkpoint and acceptance map.

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD: `a74f7429ba109f56529516b404abaf92faae99ea`.
- Assigned base: `cf4a562b65e0f459eec8e77e8b10ca7aa4f847d0`.
- Job: `617c8e0536a54be8b6a065a42827903e`.
- Starting working tree clean; empty salvage diff preserved outside the worktree.
- Process the explicit vulture exact-debt-ledger gate, then focused existing soak/admission/persistence tests and acceptance evidence. Candidate edits are this report, `quality/vulture-baseline.json` only for observed reviewed retained identities, and source/test/inventory files only if the gate demonstrates actual dead code requiring repair. No execution-authority redesign or production rate-limit redesign is in scope.
- Inspect existing `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, load profile/evidence docs, production rate middleware, adjacent persistence/task tests and relevant accepted ADRs.
- Job directory has no `check-*.log` files at initial inspection. Do not rely on historical green claims.
- Prior result reports BLOCKED; independently validate rather than infer completion.

## Assumption and stop condition

This is a writer CI-repair round, not authorization to claim a host-uvicorn preflight is an exact production RC soak. No immutable RC image/configuration is supplied in the assignment. If production evidence remains missing, record it as UNVERIFIED and hand off blocked rather than fabricate a four-hour soak or weaken gates.

## Results

`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` passed (exit 0): 1,360 findings, 1,360 reviewed identities, 0 unclassified, 0 never-allowlist. No unbanked identity was reported, so no source deletion or ledger amendment is justified. The historical shared-store limiter claim is already corrected at the assigned HEAD; no duplicate cosmetic repair is needed.

Focused validation passed: `uv run ruff check .`; `uv run ruff format --check .` (2,809 files); `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs` (88 passed, 5 skipped in 3.28s). The five skips require `MAISTRO_TEST_PG_DSN`; no live PostgreSQL validation is claimed. The passing tests include both authenticated and unauthenticated production-middleware counterexamples: replica 2 admits two more requests after the same identity exhausts replica 1.

Architecture review this round: accepted ADR-081226-a66b retains canonical Run/NodeRun/Attempt lifecycle ownership; ADR-081626-f383 requires durable Attempt fencing and explicitly distinguishes it from expiry/takeover. ADR-085 requires principal-keyed rate limits but does not establish shared replica state. ADR-081 is Proposed, not an accepted waiver of production evidence. Preserve Goal → Graph → Run → NodeRun → Attempt; neither admission uniqueness nor process exit proves physical side-effect uniqueness. No competing authority is introduced, and no acceptance criterion is waived.

Imported the current driver using `uv run python` and ran `failed_promotion_checks` over the four frozen historical packs. Assertions that each fails `sustain_duration` and `exact_rc_artifact` passed:

| Evidence file under `evidence/` | Recorded sustain seconds | Failed gates |
|---|---:|---:|
| `m3a-soak-evidence.json` | absent | 7 |
| `m3a-repair-validation.json` | absent | 7 |
| `m3a-round5-final.json` | 90.17 | 3 |
| `m3a-round6-shakedown.json` | 90.43 | 2 |

This evaluates recorded evidence, not the truth of every historical passing flag. The current driver (`scripts/soak/run_soak.py:635`) explicitly rejects exact-RC equivalence. Production `maistro_server/main.py:588` installs the middleware whose constructor allocates a separate in-memory limiter (`api/rate_limit.py:72`). The reference Compose (`deploy/docker-compose.prod.yml:26-62`) declares two application replicas, but local builds and mutable dependency tags are not an identified immutable RC.

Additional gates passed (exit 0):

- `uv run python scripts/check-deployment-claims.py`
- `uv run python scripts/check-execution-lifecycles.py` (19 discovered/classified lifecycles)
- `uv run python scripts/check-merge-markers.py`
- `git diff --check`

Fresh command output is retained in the job directory under
`/home/dev/maistro/jobs/617c8e0536a54be8b6a065a42827903e/`:
`vulture.log`, `pytest.log`, and `evidence-check.json`. The latter records the
current evaluator's failures for the four fixed historical packs; it is not a
new soak. No driver `check-*.log` files were available. These results were
executed independently, not copied from the previous BLOCKED result.

## Acceptance disposition

| Criterion | Current evidence / disposition |
|---|---|
| Representative RC profile | PARTIAL: existing profile has request mix and thresholds, but explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model, Design/Canvas and Goal/background workloads. RC applicability UNVERIFIED. |
| At least two application replicas | Reference Compose inspected; actual exact-RC replica deployment UNVERIFIED. ASGI instances do not count as deployed replicas. |
| Sustained saturation, queue growth, reclaim, retry, leaks | UNVERIFIED: no sustained run executed; all four historical packs rejected. Subprocess sampler regression is not long-window observation. |
| Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED: profile's schedule probe admits then cancels a queued Run; admission uniqueness does not prove physical Attempt or side-effect uniqueness. |
| Rate/security/degraded behavior and replica non-bypass | NOT MET for aggregate principal allowance: executed production middleware regression proves a second allowance on the second replica for both authenticated and pre-auth identities. Full security/degraded behavior under RC load UNVERIFIED. |
| Complete metrics with explicit thresholds | PARTIAL: process-group sampler regression passes; complete application event-loop latency, worker census and RC metrics/threshold validation UNVERIFIED. |
| Active-work kill/restart drain/fencing/recovery | UNVERIFIED: no replica restart executed this round; historical rejoin/terminal counts do not prove physical-work recovery. |
| Long-running exact-RC soak; rerun after runtime/config change | BLOCKED: no designated immutable RC/configuration; current runner is explicitly not a promotion runner. No four-hour exact-RC soak executed. |
| Findings filed/reclassified to earliest invariant | PARTIAL: existing F11/F12 records classify M3-A evidence defects. External filing UNVERIFIED; GitHub mutations prohibited. |
| Machine/human evidence tied to exact hashes | PARTIAL: historical packs preserved and evaluated, but qualifying RC image/package/config hashes and soak evidence UNVERIFIED. |

## Handoff

**BLOCKED**, not integration approval. The requested CI failure does not reproduce. The prior block is missing release evidence and an observed rate-limit contract mismatch, not a merge conflict or unbanked vulture debt. Changing the ledger or re-running a short host-process soak cannot resolve it.

Only this report changed. No new tests, no inventory delta, no source/runtime-config, ledger, grant or historical evidence edits. No GitHub mutations.

Next owner must designate immutable RC images and configuration, establish the applicable representative workload, resolve the replica aggregate-limit mismatch without a parallel authorization path, provide a production-topology runner with physical Attempt correlation and full application telemetry, then execute at least four hours on that unchanged artifact/configuration. Runtime/config changes invalidate the run.

Progress: checked 1 assigned issue; done 0 (acceptance blocked); skipped 0 issues; errors 0 executed checks; 5 PostgreSQL tests skipped. Local commit records this checkpoint; the issue remains unresolved.
