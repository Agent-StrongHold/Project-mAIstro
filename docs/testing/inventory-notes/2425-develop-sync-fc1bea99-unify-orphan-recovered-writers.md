---
inventory-delta:
  packages/maistro-core/tests: -6
---

# 2425-develop-sync-fc1bea99-unify-orphan-recovered-writers

Develop sync (merge of `fc1bea9936`, `origin/develop` = #2420 tip) into the
#2425 / P4b branch. Develop's #2417 / P3b landed `recover_orphaned_attempt` —
a superset of this branch's P4b `recover_leaseless_orphaned_attempt`: the same
CREATED/RUNNING + lease-less + no-prior-cause guards and the same
CANCELLED+RECOVERED stamp, plus `owning_run_id` lineage enforcement and a
canonical `RunStore` write-authority path the branch's leaf lacked.

Resolution unifies on develop's writer:

- `maistro/runs/lifecycle.py`: branch leaf removed; `ORPHANED_ATTEMPT_ERROR`
  and `recover_orphaned_attempt` kept (develop's spelling).
- `maistro/graph/durable_runs/execution_store.py`: durable adapter keeps only
  `recover_orphaned_attempt` (canonical authority when wired; lineage-checked
  local mode otherwise).
- `maistro/graph/durable_runs/attempt_executor.py`: `_reconcile_orphaned_attempts`
  now skips leased rows (reclaim path owns them) and calls the unified writer
  with `owning_run_id=record.run_id`.
- `maistro/runs/store.py` / `sqlite_store.py` / `pg_store.py`: both-side
  additions kept — P4a `apply_recovered_attempt_disposition` (#232 P4a) and
  P3b `recover_orphaned_attempt` coexist.
- `packages/maistro-rsi/tests/test_m8a16_lean_rust_kernel_research.py`:
  kernel classification keeps only `recover_orphaned_attempt` (the classified
  set must name exactly the functions `lifecycle.py` defines).
- `packages/maistro-core/tests/runs/test_recover_leaseless_orphaned_attempt.py`
  **deleted (-6)**: every node is subsumed by develop's
  `test_recover_orphaned_attempt.py` (construction happy paths incl. default
  `ORPHANED_ATTEMPT_ERROR`, leased/terminal/non-active/preexisting-cause
  refusals, store + spine persistence, PG lock refusals). The three durable
  `DurableRunExecutionStore` P4b cases in
  `tests/graph/durable_runs/test_canonical_execution_store.py` survive with
  call sites moved to the unified API.

The branch's P4b acceptance surface is unchanged: reconciler persisted-cause
authority (`reconciliation.py` untouched by the merge), typed RECOVERED →
`apply_recovered_attempt_disposition` parking, and recovered-provenance tests.

## Verification evidence (develop-sync resolution round, merge head 08cf53c127)

- Conflicts resolved in place (8 files); `ruff check .` all green;
  `ruff format --check .` 3616 files green (one merge-seam blank line
  reformatted in `execution_store.py`).
- Battery: canvas `test_canonical_execution.py` + full
  `maistro-core/tests/graph/durable_runs/` + the seven disposition/provenance
  runs suites + `maistro-rsi` kernel classification — **1273 passed / 220
  skipped / 4 xfailed** (was: collection SyntaxError at the conflicted head).
- Full `packages/maistro-core/tests/runs/`: **1635 passed / 399 skipped**.
- hive-conductor backend merge-touched suites (durable approval, materialized
  authority, wiring, routes, adapter): **115 passed**.
- `scripts/check-suite-inventory.py`: ok, 21 suites (after the `-6` delta
  above); driver's per-suite collection failures at the conflicted head
  (hive backend, maistro-rsi) all collect cleanly again.
- CI-exact vulture ledger (`packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`): exit 0, 1222 reviewed identities.
- `check-owned-store-access.py`, `check-test-duplicates.py`,
  `check-promotion-surface.py`: all ok.
- mypy `packages/maistro-core/src`: single pre-existing `maistro_bootstrap.cli`
  import-not-found (optional extra, untouched file; present at develop
  fc1bea9936) — no new errors.
- Acceptance re-read at merged head: `reconciliation.py:281-301` persisted
  cause is authoritative (unknown cause → `RunIntegrityError`, no RECOVERED
  fallback; caller cause must equal persisted; typed RECOVERED parks via
  `apply_recovered_attempt_disposition`); `attempt_executor.py` leaseless
  orphan path uses the canonical-authority `recover_orphaned_attempt` writer.
