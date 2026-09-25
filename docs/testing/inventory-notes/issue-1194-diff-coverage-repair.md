---
inventory-delta:
  packages/maistro-core/tests: +27
  packages/maistro-server/tests: +1
---
# issue-1194-diff-coverage-repair

The #1194 replay-contract branch landed with the diff-coverage gate red: nine
changed source files sat below the 90% lines / 80% branch-arc floors because
their new guard arms, recovery paths and wiring branches had no test driving
them. This change adds the 27 maistro-core and 1 maistro-server tests that
close exactly those gaps — no production code was altered, and no coverage was
gamed: every test exercises a reachable behavior through public entry points.

- **Logical effect claims on all three Run stores** (`test_store.py`,
  `test_sqlite_store.py`, `test_pg_store_internals.py`): admit-once/replay,
  empty-key refusal, `find_run_by_effect` miss, claim without a parent chain,
  claim bound to a parent Run + NodeRun, a parent NodeRun from another Run, and
  a NodeRun named without its parent Run. The SQLite store's mid-transaction
  unique-index conflict recovery and the PostgreSQL store's
  `INSERT ... ON CONFLICT` race adoption are covered the way this file already
  covers Attempt races — by standing in for the concurrent committer the write
  lock/transaction otherwise serializes away, plus the
  conflicting-constraint-with-no-winner integrity failures.
- **Invocation ledger** (`test_invocation_store.py`): the SQLite
  `list_effect(node_run_id=None)` logical-effect lookup (the branch's bandit
  fix made it a second literal statement), and an admission race whose
  canonical re-read finds no COMPLETED winner — the original
  `UnsafeEffectRetry` must stand rather than fabricate a replay.
- **Container wiring** (`test_pg_invocation_store.py`): with a PostgreSQL pool
  wired, `_wire_capability_invocations` selects and schema-ensures
  `PgInvocationStore` rather than a fallback.
- **Executor replay policy** (`test_executor_gaps.py`): an EFFECT_KEY node
  without a logical Run/node identity is not revisited even with retry budget
  left — the contract's precondition, not just its missing-key arm.
- **`compliance.block`** (`test_wait_hitl_negative_kinds.py`): replay replaces
  only its own logical penalty and leaves a foreign penalty untouched (the
  replace-scan arc).
- **A2A admission** (`test_a2a_api.py`): unconfigured admission endpoints
  refuse with 503 instead of admitting against guessed stores.

With this change the branch's diff-coverage audit reports every measured file
at or above the floors (`check-diff-coverage.py` against the merge base).
