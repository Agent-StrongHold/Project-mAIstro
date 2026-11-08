# Issue #860 — bounded repair 401ed7a8

## Frozen scope

- Issue #860 only; branch `auto-860`, starting head
  `b9a66ec4ece455085ff4fe2f349fd67e5e5e5552`, supplied base
  `2154f845347c9541016288c760f8da3f5cd2e064`. Starting worktree clean.
- Inputs: supplied dispatch-context.json, prior result cea7e4fc, and failed
  check-3.log from job 98a11313. No check-*.log exists in the current job.
- Process the reported schema-fence failure and exact vulture gate, then
  validate #860 acceptance against the existing harness and tests.
- Candidate implementation scope: pg_learnings.py and its persistence test,
  scripts/soak/run_soak.py and tests/test_soak_promotion_gates.py;
  quality/vulture-baseline.json only for observed retained identities;
  this report and a test inventory note if tests change. No unrelated repairs.
- Ambiguity: assignment is a writer repair despite generic verifier language.
  Proceed as writer. No production RC artifact/configuration was designated in
  the assignment; do not label local preflight as an exact-RC production soak.

## Progress

Snapshot recorded. Prior failure describes 21 expected DDL statements versus
24 executed; this must be reproduced before changing code or expectations.
Prior result is BLOCKED, not promotion evidence.

Fresh reproduction (1,200-second timeout): the exact vulture command passed,
1,323 reviewed identities / findings, zero unclassified or never-allowlist.
`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
passed: 37 passed, 6 skipped. Neither historical failure warrants a speculative
source or ledger edit. Production acceptance remains separate from CI success.

## Architecture and executed validation

Read repository instructions and docs/README.md; Accepted ADR-081426-1f7c
makes Attempt the physical execution identity, ADR-081626-f383 requires durable
lease fencing and explicitly does not itself define reclaim, and ADR-085 makes
request limits per principal. Preserve `Goal -> Graph -> Run -> NodeRun ->
Attempt`. Admission/cancellation is not physical execution evidence; local rate
limits cannot establish the stronger replica-selection acceptance criterion.
No architectural authority or gate was changed.

The schema test at `packages/maistro-core/tests/persistence/test_pg_learnings.py:175`
already includes all three Gauntlet columns omitted in the historical failed
log. Production `pg_learnings.py:215` takes the advisory lock inside the
transaction before those upgrades. This is unit evidence, not a new concurrent
PostgreSQL boot experiment; six database-dependent tests skipped.

Additional fresh commands, each in a batch with a 1,200-second timeout:

| Command | Result |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3,277 files |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs` | 81 passed |
| `uv run python scripts/check-backlog-consistency.py` | PASS, 168 items |

## Acceptance disposition

| Criterion | Executed evidence or remaining gap |
| --- | --- |
| Representative RC workload | **UNVERIFIED**. Read `m3a-load-profile.md`: single-key degraded preflight lacks concurrent Workspace population, Graph fan-out, successful model/tool and Design/Canvas mix. No selected immutable RC/config supplied. |
| Two deployed application replicas | **UNVERIFIED**. ASGI replica tests passed, but no deployed RC pair exercised this round. |
| Sustained saturation, queues, reclaim, retries, leaks | **UNVERIFIED**. Focused unit/regression tests do not observe sustained production behavior. |
| No duplicated physical work and Goal reconciliation | **UNVERIFIED**. `scripts/soak/run_soak.py:1067` cancels the admission probe without executing its Run. Canonical physical work needs its own oracle. |
| Replica-selection non-bypass/security/degradation | **UNVERIFIED** for production guarantee. Executed `tests/test_soak_promotion_gates.py:439` counterexample: same principal gets `[200, 200, 429]` independently on each production middleware instance, for both identity classes. Passing local enforcement probes cannot prove this criterion. |
| Complete telemetry and thresholds | **UNVERIFIED**. Process-group sampler tests passed, but no production query/application-loop/worker/queue time series collected. Driver-loop timing is not application-loop timing. |
| Active-work restart, drain, fencing, recovery | **UNVERIFIED**. No active-work production kill/restart experiment performed. |
| Long-running exact-RC/config soak | **UNVERIFIED**. `scripts/soak/run_soak.py:744` rejects host preflight as exact RC. Executed missing/null/preflight CLI regressions verify failure even for synthetic four-hour evidence. |
| Findings classified before promotion | **UNVERIFIED** for completeness. Backlog consistency passed; this round produced no representative load experiment or GitHub mutations. |
| Human/machine evidence tied to exact hashes | **UNVERIFIED** for production soak. This report records source validation, not an image/config-bound production observation bundle. |

## Final handoff

**BLOCKED**. Historical CI failure no longer reproduces; exact vulture scan
requires no ledger amendment. Only this report changes. No tests added, so no
inventory delta. No speculative source fixes, gate weakening, or GitHub actions.
Inherited branch changes beyond the frozen scope are not certified.

Next: designate immutable promoted RC/config and representative workload, resolve
replica-selection enforcement semantics, then run canonical physical-work and
active-recovery probes with full telemetry for the qualifying long soak. Another
retry of the same stale schema/vulture failure cannot satisfy these criteria.

Progress: checked 1 issue, acceptance-complete 0, skipped 0 issues, validation
errors 0. Local report commit is the checkpoint, not integration approval.
