---
inventory-delta:
  packages/maistro-core/tests: +20
---

# P2d CI repair: backend + race coverage the first draft missed (#2369 / #232)

The merge-queue evaluation at 5a03603fee failed the diff-coverage gate on five
source files whose changed lines no test exercised: the SQLite and PostgreSQL
`compensate_unlaunched_attempt` bodies (the first draft proved the leaf on the
in-memory store only), the durable graph store's local-only compensation path
and its canonical-reclaim `AttemptNotFound` translation, the executor's
refusal-race handler in `_terminalize_if_open`, and the batch re-check skip
guards both reclaim loops carry. Same failure shape as the P2b repair
(#2358): a store-level seam proven on one backend is not yet proven.

## Collected node IDs

`packages/maistro-core/tests/runs/test_compensate_unlaunched_attempt.py` (+12):

- `TestCompensateSpine` on the three-backend `spine` harness (memory /
  SQLite / PostgreSQL): persist CANCELLED+RECOVERED under a matching fence;
  stale fence refuses and writes nothing; RUNNING winner is refused; missing
  id raises `AttemptNotFound`

`packages/maistro-core/tests/runs/test_reclaim_expired_attempt_exact_id.py` (+2):

- batch re-check skips an attempt removed after the snapshot (in-memory
  map seam): `current is None` is a skip, not a crash or a rewrite
- batch re-check skips an attempt renewed underneath it (SQLite awaited
  re-read): no rewrite of live work — the in-memory renew leg is develop's
  predicate-stub test, merged from #2358's CI repair; this branch dropped
  its duplicate

`packages/maistro-core/tests/graph/durable_runs/test_canonical_execution_store.py` (+3):

- local-only compensation (no canonical RunStore wired) commits
  CANCELLED+RECOVERED, refuses a stale fence, raises `AttemptNotFound`
  (the canonical-reclaim vanish translation itself is develop's
  `_VanishingAttemptRunStore` test, merged from #2367's CI repair — this
  branch dropped its duplicate in favor of develop's)

`packages/maistro-core/tests/runs/test_execution.py` (+3):

- prelaunch compensation losing to a RUNNING winner re-raises and stamps
  nothing
- prelaunch compensation losing to a requested-CANCELLED winner returns
  `(refreshed, False)` and keeps the winner's cause
- prelaunch compensation on a vanished attempt is a `RunIntegrityError`
