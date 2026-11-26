# auto-42 round: develop sync to 3f8ccbe9 resolved; issue #42 acceptance re-proven at bd4df463e

Repair round for lane L42 (M1-B2 — Finish Attempt → ExecutionRuntime physical
execution integration). **No tests added or removed**: the note carries no
`inventory-delta` key at all, and the gate reads an absent key as zero
movement.

## What this round did

1. **Resolved the preserved develop sync conflict.** The worktree arrived with
   an in-progress merge of `origin/develop` (`3f8ccbe9d40d`, M9-H2 ext-harness,
   #2016/#974) into `auto-42` (`1b69e1a5967f`), blocked on exactly one file:
   `docs/testing/inventory/baseline.json`. Resolution keeps the branch-side
   raised counts (`formal/` 664, `packages/hive-conductor/backend/tests` 2937)
   and takes develop's new suite row `packages/maistro-ext-harness/tests: 0`
   — whose whole `+138` arrives via `974-ext-host-harness.md` (expected =
   0 + 138). Merge committed as `bd4df463e608`; worktree clean afterwards.
2. **Verified the merge lost no ledger rows.** Per the numstat rule:
   `git diff --numstat` of `quality/` against both parents shows the merged
   tree byte-identical to the branch parent, and develop made **no**
   `quality/` changes vs the merge base (`bc40b6cdad46`) — nothing to lose.
3. **Scoped the sync delta:** `git diff --name-only 1b69e1a59 bd4df463e`
   touches only the new `packages/maistro-ext-harness` package, gate/scripts
   enrollment, workflows, `pyproject.toml`/`uv.lock`,
   `extensions/namespace-policy.json`, and inventory docs — **zero lines** in
   `maistro-core`/`maistro-server`/`maistro-canvas`, so all prior issue-#42
   evidence at `fd2eddfa3`/`1b69e1a59` transfers to code that is byte-identical,
   and the batteries below re-prove it live at the merged head anyway.

## Gates re-run at bd4df463e (base now 3f8ccbe9d40d)

- `uv run ruff check .` — pass. `uv run ruff format --check .` — 3084 files
  formatted, pass.
- Exact vulture CI recipe (`check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`): 1332 reviewed identities
  ↔ 1332 findings. **No ledger amendment made; none needed.**
- `check-reachability.py` — pass. `check-execution-lifecycles.py` — 19/19
  classified. `check-foreign-harness-egress.py` — exit 0.
  `check-wiring-reads.py` — 11 unread matched, ledger matches.
- `check-suite-inventory.py` (all suites, no args — CI's invocation): 17
  suites ok, 27903 unique node IDs, 0 duplicates — including the merged
  ext-harness suite at exactly 138.
- Prior verify job's exact pytest battery (canvas publishing, A2A, capabilities
  incl. pg_*, durable-runs executor/replay-guard, remote delegate family,
  spine conformance, sqlite store, task restart recovery): **684 passed,
  131 skipped** (pg legs skip locally without a DSN; proven live below).

## Issue #42 acceptance — live evidence at bd4df463e

- **Attempt identity, retry chronology, replay guard, cancellation, chat
  leases.** `graph/durable_runs/test_node_retry_attempts.py`,
  `runs/test_execution_is_correlated.py`,
  `runs/test_attempt_cancellation_cause_model.py`,
  `runs/test_chat_attempt_recovery.py`,
  `runtime/test_public_cancellation_fence.py`: **69 passed**. Seams confirmed
  in source: `runs/execution.py:395` persists the Attempt before launch and
  `:594` passes `execution_id=attempt.attempt_id` into `ExecutionRuntime.execute`;
  `runs/chat_execution.py:212-224` joins chat via `RunExecutionService` with a
  real `lease_ttl` (#1170).
- **durable_runs + runs suites (full)**: **1762 passed, 295 skipped**.
- **New merged suite**: `packages/maistro-ext-harness/tests`: **138 passed**
  (matches the develop note's +138).
- **Persistence/Events correlation on live PostgreSQL** (pgvector:pg18 via the
  rootless docker socket, `alembic upgrade head` → 058, DSN as plain
  `postgresql://` — `to_async_url`/`to_asyncpg_dsn` normalize per consumer):
  restart E2E + pg invocation/approval/contention: **33 passed, 0 skipped**
  (the worker-death SigKill restart E2E actually ran; also passes alone in
  7.65s); `tests/persistence` + `test_container_postgres.py` +
  `builders/test_migration_parity.py`: **828 passed, 84 skipped**;
  `alembic downgrade base` + `upgrade head` reversible on the same database.
  Container removed afterwards; no repository or remote residue.
- **Dependency closure (criterion 8).** Dispatch snapshot
  (2026-10-06T18:47Z): #1169 closed/completed 2026-09-13, #1170 2026-09-10,
  #1194 2026-09-29. No GitHub mutations performed.

## Residual risks (unchanged in kind from the prior round)

- **Host-load sensitivity of the spawned-server E2E.** In 8 combined runs of
  the pg battery, one interleaving produced 2 failures + 1 setup error with a
  210s wall (vs 9s quiet-host, 121-243s under load) while two *other lane
  drivers* were in D-state on this host; the failure did not reproduce in any
  of the 7 other runs, the test passes alone, and `_wait_ready`'s 120s
  startup budget plus the 30s per-test timeouts are load-shaped limits. No
  correctness signal against the merged tree; CI runs these files with the pg
  legs skipped. Recording rather than repairing: any fix belongs to the
  suites' shared-database hygiene, outside this issue's scope.
- #232 (task Attempt recovery production soak) remains open upstream; the
  restart E2E passes on live PostgreSQL here, but continuous soak is not
  proven locally.
- The maistro-design Hypothesis property-test contradiction recorded in the
  `fd2eddfa3` round is an upstream develop matter, unchanged here.
