# Issue #860 — bounded CI repair 3036db40

## Frozen scope

- Issue #860 only; assigned branch `auto-860`, clean starting head
  `720cd85494f76586947664365a259ae2b836c491`; supplied base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Inputs: supplied dispatch snapshot, prior result bdc6828f, prior check-3.log.
  No current-job check logs were present at initial inspection.
- Repair candidates: `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  adjacent `src/maistro/persistence/pg_learnings.py`, and reviewed identities in
  `quality/vulture-baseline.json` only if the exact requested scan finds debt.
- Validation context: existing `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, production rate middleware, load profile,
  relevant ADRs and CI gate definitions. No other issues/PRs will be processed.
- This report and, if tests change, a corresponding inventory note are in scope.

## Initial evidence and assumptions

The supplied check-3.log reported 24 schema statements versus 21 expected.
The prior result reports release-evidence gaps, not a develop merge conflict.
Assumption: reproduce before editing; do not fetch/merge or expand into another
issue's runtime redesign. Canonical Goal -> Graph -> Run -> NodeRun -> Attempt
and accepted ADR authority must remain unchanged.

## Executed checkpoint

- `uv sync --locked --extra dev`: passed.
- Exact requested vulture scan: passed, 1323 findings / 1323 reviewed identities,
  zero unclassified and never-allowlist findings; selected base `4aa68edc0b6b`.
  No scanner evidence justifies a ledger amendment.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py -x -q`:
  **102 passed, 6 skipped**. The supplied historical failure does not reproduce:
  the existing test already includes the three Gauntlet audit columns.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3270 files formatted.
- `uv run python scripts/check-suite-inventory.py`: passed, 17 suites,
  31128 unique identities, no duplicated evidence.

- `uv run pytest tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **9 passed**.
- `uv run python` imported the current soak evaluator and asserted that
  `docs/testing/soak/evidence/m3a-round30-shakedown.json` fails exactly
  `sustain_duration` and `exact_rc_artifact`: passed. Recorded duration is
  420.08 seconds, not the required 14400 seconds. Also asserted the current
  preflight artifact check remains false. This is historical-data evaluation,
  not a fresh soak.
- `git diff --check`: passed before final report completion.

No test or production change warranted by these CI findings. No tests added or
removed; no inventory delta required. Only this report changes in this round.

## Architecture reconciliation

Read accepted ADR-081226-69ee (Graph/Node execution), ADR-081626-f383 (Attempt
lease fencing), ADR-082126-f69c (recurrence produces Runs), documentation
hierarchy, production schema fencing and rate middleware, soak driver, load
profile and adjacent regression tests. Preserve the canonical execution model;
do not introduce a second scheduler or authorization path to satisfy this issue.
The lease ADR expressly does not define expiry takeover. The issue's reclaim
criterion must be demonstrated through accepted canonical recovery authority,
not implemented as an implicit timeout takeover in the soak harness.

## Acceptance review

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC profile | **UNVERIFIED.** `m3a-load-profile.md:152` explicitly lacks concurrent users/Workspaces, fan-out, successful model/tool, Design/Canvas and Goal/background workloads. No designated immutable RC inclusion/exclusion contract supplied. |
| Two application replicas | **UNVERIFIED for RC.** Boot-contract tests pass, but ASGI instances/host processes are not the promoted deployment. |
| Sustained saturation, queue, expiry/reclaim, backoff, memory/descriptor/process leaks | **UNVERIFIED.** Historical data fails duration. Sampler tests pass but do not prove long-window workload behavior. |
| No duplicate physical work and Goal reconciliation | **UNVERIFIED.** `run_soak.py:1044` cancels the schedule admission probe without execution. Receipt deduplication tests do not establish physical Attempt uniqueness. |
| Security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED overall; contrary rate evidence reproduced.** `test_soak_promotion_gates.py:439` executes real production middleware and observes independent `[200,200,429]` allowances for the same identity on each instance, for both authentication classes. `api/rate_limit.py:32` documents this process-local policy. No new shared limiter or auth path is authorized here. |
| Full telemetry and explicit thresholds | **UNVERIFIED.** Real child-process sampler test passes; driver loop lag and a driver SELECT 1 probe are not application-loop and production-query latency. Missing saturation/reclaim/worker and long-window proof remains documented in the profile. |
| Kill/restart under active work proves drain/fencing/recovery | **UNVERIFIED.** Boot cleanup tests pass but no deployed active-work restart was executed. Process rejoin alone is not fencing proof. |
| Long soak of exact unchanged RC | **BLOCKED / UNVERIFIED.** `run_soak.py:730` always rejects its host topology; four-hour synthetic gate tests fail closed. Current evaluator rejects historical 420.08-second evidence. No exact RC artifact/configuration supplied. |
| Findings filed/reclassified before promotion | Limitations documented locally. External milestone disposition **UNVERIFIED**; no GitHub mutation permitted or performed. |
| Published machine/human evidence tied to image/package/commit/config hashes | Historical preflight evidence exists, but exact-RC publication **UNVERIFIED**; tests and old evidence cannot supply missing artifact identity. |

## Final handoff

**BLOCKED**, not merge-ready. The historical test failure is already repaired
at the starting head; the requested ledger scan is clean. No evidenced CI repair
remains to apply. Repeating the same validation cannot supply missing release
artifacts or transform the preflight into an RC runner.

Next requires the designated immutable RC image/configuration and a production
runner covering the representative workload, canonical physical-work/Goal
correlation, complete telemetry and active-work restart protocol. Resolve the
replica-selection policy discrepancy before the at-least-four-hour exact-RC
soak. No acceptance waiver, integration approval or issue closure is implied.

Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC prerequisites}`.
Commit this report locally. No production/test/ledger changes, no push, no
GitHub mutations, and no inherited work discarded.
