# Issue 860 repair — cea7e4fc

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD: `bbbdbd30e162a62438a1ef2be2108b8e7c69e9c4` (verified); clean worktree.
- Supplied comparison base: `2154f845347c9541016288c760f8da3f5cd2e064` (resolved).
- Evidence: supplied dispatch-context.json, prior result f5c5b9da, prior check-3.log from 98a11313. No check-*.log exists in this job's initial directory listing.
- Frozen candidate repair files: `packages/maistro-core/tests/persistence/test_pg_learnings.py`, `packages/maistro-core/src/maistro/persistence/pg_learnings.py`, `quality/vulture-baseline.json` (only if actual scan warrants), `docs/testing/inventory-notes/m3a-860-merged-schema-fence.md`, and this report. Inspect soak runner/tests, relevant ADRs and CI gate implementation as evidence only.
- Ambiguity: dispatch repeats an old schema-test failure but prior result reports production soak blockers. Reproduce both the named failure and exact vulture scan; do not manufacture a repair if already fixed. Existing large branch/base divergence is not a develop-sync conflict and is outside this focused repair.

## Initial evidence

Prior check-3.log expected 21 DDL statements but observed 24. Fresh reproduction: `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` passed (37 passed, 6 skipped). Lines 175–177 already cover the three Gauntlet columns missing from the historical log. No source/test repair justified.

Fresh exact vulture command: `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` passed: 1,323 reviewed identities/findings, zero unclassified or never-allowlist findings. No ledger amendment justified. Both commands had 600-second timeout.

The prior production acceptance block is separate from these already-resolved CI findings.

## Architecture and fresh validation

Read repository instructions, the documentation authority map, Accepted ADR-085 and ADR-082826-b601, and Proposed ADR-081. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`. Accepted consumer semantics require actual execution via canonical NodeRun/Attempt, not admission followed by cancellation. The preflight profile's documented process-local rate semantics do not establish the issue's stronger replica-selection non-bypass criterion. No competing scheduler, store, event or authorization authority is introduced.

Fresh commands (1,200-second timeout):

| Command | Outcome |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3,277 files |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs` | 81 passed |
| `uv run python scripts/check-backlog-consistency.py` | PASS, 168 items |

The schema unit test independently checks the full ordered DDL body. Production `pg_learnings.py:215–222` fences the upgrade with a transaction-scoped advisory lock. This is not a fresh PostgreSQL concurrent-boot experiment; six DB-dependent tests skipped.

## Acceptance matrix

| Issue criterion | Evidence and disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED**. `docs/testing/soak/m3a-load-profile.md:46–82` defines one-key degraded traffic, not the required multi-user/Workspace, Graph fan-out, successful model/tool, Design/Canvas and background-worker mix. |
| At least two production replicas | **UNVERIFIED**. `deploy/docker-compose.prod.yml:26–77` declares two replicas, but no deployed immutable RC pair was exercised in this attempt. |
| Sustained saturation, queue growth, reclaim, retries, memory/descriptor/process leaks | **UNVERIFIED**. Regression tests are short in-process checks, not sustained production observations. |
| No duplicated physical work; Goal reconciliation | **UNVERIFIED**. `scripts/soak/run_soak.py:1067–1077` explicitly cancels schedule admission probes without execution. Accepted consumer ADR forbids treating admission as execution proof. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED** for deployment; counterexample reproduced. `tests/test_soak_promotion_gates.py:439–489` uses production middleware and observes `[200, 200, 429]` separately on both replicas for the same identity, authenticated and unauthenticated. `rate_limit.py:93` instantiates an in-memory limiter. |
| Full PostgreSQL/application-loop/worker/resource/queue/error telemetry with thresholds | **UNVERIFIED**. No production time series captured; sampler regression tests are not actual application-loop or query-latency measurements. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED**. No production active-work restart experiment executed. |
| Long-running exact RC/config soak | **UNVERIFIED**. `run_soak.py:744–755` unconditionally rejects its host preflight as exact RC. Executed promotion regression tests verify that missing/null/preflight artifact evidence cannot pass. |
| Load findings classified to earliest broken milestone invariant | **UNVERIFIED** for completeness. Backlog consistency passes, but no new representative load experiment was performed. No GitHub mutations. |
| Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED**. This report is source-validation evidence, not a hash-bound production soak bundle. |

## Handoff

**BLOCKED** on production acceptance. The historical schema failure and exact vulture gate are already resolved at the supplied starting HEAD. Only this report changes; no test addition or inventory delta, ledger amendment, or speculative source repair is appropriate.

Required next work: select the immutable RC artifact/configuration and representative workload, resolve replica-selection enforcement semantics, execute physical-work/recovery oracles through the canonical spine, and capture complete telemetry over a qualifying long soak. A repeated CI-repair dispatch with this same historical failure cannot establish these criteria. The large inherited branch/base divergence was not certified by these focused checks.

Progress: checked 1 issue, acceptance-complete 0, skipped 0 issues, validation errors 0. Local report commit is the checkpoint; no integration approval or issue closure is implied.
