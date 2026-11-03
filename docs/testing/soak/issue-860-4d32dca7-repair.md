# Issue #860 repair — job 4d32dca7

## Frozen scope

- Only issue #860, branch `auto-860`, starting head
  `814335919412ca34c5b5e8ed70670a1ca8c98626`, assigned base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Clean starting worktree; no incoming work to salvage.
- Inspect repository guidance, ADRs, existing soak harness/tests and supplied
  dispatch/prior failure evidence. Run exact vulture CI scan and focused
  validation. Change retained-identity ledger only if fresh scan requires it.
- Planned output: this report; production/tests/ledger changes only if actual
  reproducible evidence justifies them within #860. No GitHub mutations.
- Current job directory has no `check-*.log` files. Supplied prior failure and
  result are historical evidence, not fresh validation.
- Ambiguity: no designated immutable promotion RC/configuration is supplied.
  Do not invent one or claim local harness runs satisfy the exact-RC criterion.

## Results

- Exact mandated vulture scan passed: 1323 findings match 1323 reviewed
  identities; zero unclassified. No ledger amendment warranted.
- Historical `check-3.log` fails the learning-schema fence assertion (24 actual
  statements versus 21 expected). Fresh run passes; the current test independently
  names all 24 statements, including the three validation-audit upgrades.
- Read accepted ADR-085 (principal request limits) and ADR-082526-b36a
  (canonical lease renewal/reclaim/fencing). Preserve the existing execution
  and authorization authorities; admission deduplication cannot substitute
  for physical-work or recovery proof.
- `docs/testing/soak/README.md`: not found; skipped. The actual profile is
  `docs/testing/soak/m3a-load-profile.md`; read it and adjacent promotion tests.
  Profile explicitly excludes exact RC identity and documents workload gaps.

## Fresh validation

Commands ran in the assigned worktree with 1200-second timeout. Logs are in
`/home/dev/maistro/jobs/4d32dca75cf14d74a884b37530e8b027/validation-*.log`.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1323 reviewed / 1323 observed, zero unclassified; matches `.github/workflows/vulture-ratchet.yml:82` arguments |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs` | 111 passed, 6 skipped, 2.78 s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS |
| `uv run python scripts/check-suite-inventory.py` | PASS |
| `uv run python scripts/check-deployment-claims.py` | PASS |

The six skips require `MAISTRO_TEST_PG_DSN` pointing to a migrated database.
No live PostgreSQL or deployed-RC validation is claimed. The schema test uses
an observing fake connection; passing it proves the DDL fence call sequence,
not a concurrent database boot. No tests were added or changed, so no inventory
delta is required. This report is the only changed file.

## Acceptance audit

| #860 acceptance criterion | Executed evidence / remaining requirement |
| --- | --- |
| Representative RC load profile | **UNVERIFIED.** Read `m3a-load-profile.md:152` and actual request mix at `scripts/soak/run_soak.py:1381`: one-key health/task/degraded traffic lacks multi-user/Workspace, Graph fan-out, successful tool/model, Design/Canvas and Goal/background workloads or RC-specific exclusions. |
| At least two deployed application replicas | **UNVERIFIED.** Production-middleware tests exercise two independent ASGI instances, not deployed RC replicas. No deployment ran this round. |
| Sustained saturation, queue growth, reclaim, retry and leak observations | **UNVERIFIED.** Passing sampler tests observe a real child process's memory/descriptors and reject missing measurements; these are not sustained application/pool/lease observations. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal operations | **UNVERIFIED.** Read `scripts/soak/run_soak.py:1044`: schedule probe cancels its queued Run without execution. Passing admission tests cannot prove physical effects or Goal reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED overall; independent allowances reproduced.** Passing `tests/test_soak_promotion_gates.py:439` observes `[200,200,429]` separately on both production middleware instances for the same authenticated or unauthenticated identity. `packages/maistro-server/src/maistro_server/api/rate_limit.py:93` creates an instance-local limiter; documented N-times aggregate allowance is not a cluster-wide budget. Six-path probe tests prove local enforcement only. |
| Full telemetry and explicit thresholds | **UNVERIFIED at RC level.** Profile has thresholds but no fresh observed RC series. `scripts/soak/run_soak.py:1410` samples driver-loop latency, not application-loop latency. Worker, queue, pool and lock behavior under sustained RC traffic remain unproven. |
| Active-work kill/restart proving drain/fencing/recovery | **UNVERIFIED.** Boot/promotion tests pass, but no active-work kill/recovery experiment ran. Rejoin and terminal status counts alone are insufficient. |
| Long unchanged exact-RC soak | **BLOCKED / UNVERIFIED.** Source head/base are designated, not immutable promotion image/runtime configuration. `scripts/soak/run_soak.py:730` returns `exact_rc_artifact.ok=false`; freshly passing CLI regressions reject even four-hour synthetic preflight evidence. |
| Findings filed/reclassified before promotion | Local audit committed; external filing/reclassification **UNVERIFIED** (GitHub mutations prohibited). Historical schema failure does not reproduce; no current vulture mismatch. |
| Machine/human evidence bound to exact artifact/config hashes | **UNVERIFIED.** Fresh test/gate logs and this report are source-validation evidence, not a deployed-RC soak bundle. |

## Architecture reconciliation and disposition

Retain `Goal -> Graph -> Run -> NodeRun -> Attempt`. Accepted lease ADR requires
real liveness/renewal and fenced recovery; no parallel scheduler or execution
path may manufacture proof. ADR-085's principal identity contract does not turn
process-local allowances into a shared budget. Resolve that deployment contract
explicitly rather than weakening the soak gate or introducing a second auth path.

**BLOCKED:** no speculative source, test or ledger repair is justified by the
supplied historical failure and fresh passing checks. No merge conflict exists.
No Docker-availability limitation is asserted. No new host-process smoke run was
started because it cannot meet the exact-RC criterion regardless of duration.

Next: designate the immutable RC image and runtime configuration, complete the
representative workloads/physical-effect and recovery oracles/application
telemetry, resolve replica-budget semantics, then run the unchanged deployed RC
for at least 14400 seconds and publish hash-bound machine/human results. Repeating
the stale schema/vulture repair cannot supply those prerequisites.

Checkpoint: checked 1 issue; acceptance-complete 0; skipped issues 0; validation
command failures 0; 6 reported live-PG test skips. Local commit is a blocked writer
handoff, not integration approval.
