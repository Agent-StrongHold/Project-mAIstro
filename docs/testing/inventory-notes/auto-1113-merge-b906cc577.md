---
inventory-delta:
  packages/hive-conductor/backend/tests: -2
---
# auto-1113 merge reconciliation: develop b906cc577 meets the fail-closed spine

Third `develop` merge into `auto-1113` (#1113 retirement of the Hive
standalone pre-convergence Graph execution fallback), merging origin/develop
at `b906cc577fbb` (atomic canonical username allocation, #1453; canonical
manual-fire occurrence identity, #1120; HITL workspace-object authorization,
#1392; attention projection route). Five conflicted files; all resolved for
the #1113 fail-closed contract that the merged architecture gate
(`test_graph_spine_architecture_gate.py`) enforces: no shipped module may
name `InMemoryDurableRunStore` or the `_fallback_*` module globals, so
develop's `_fallback_run_store` + `get_canonical_run_store` split cannot
stand.

- `services/dag_agents.py` — kept ours: `get_run_store()` returns the
  Container-owned graph projection or raises `GraphExecutionUnavailableError`
  via `_canonical_execution_stores()`; `run_registered_dag()` admits through
  `container.run_store` unconditionally. Dropped develop's
  `_fallback_run_store` / `get_canonical_run_store` pair and the human-node
  special case (dead once admission fails closed for every node kind).
- `routes/hitl.py` — kept ours: `_store()` maps
  `GraphExecutionUnavailableError` to the documented 503 (#1113); develop's
  RuntimeError variant is subsumed.
- `docs/architecture/CONVERGENCE-MATRIX.md` — merged the recurrence/schedules
  row: canonical admission for recurring ticks and manual `fire_now`
  (#231/#1120, #251 consumer tick) AND since #1113 the standalone tick's
  `run_registered_dag` call reports `unavailable` without the Container's
  canonical stores, leaving the occurrence owed.
- `tests/test_dag_agents.py` — kept the canonical-container fixture +
  fail-closed tests; dropped develop's two weaker no-spine tests (they
  asserted the RuntimeError/fallback contract #1113 retired); the surviving
  `test_an_unavailable_engine_does_not_select_a_private_graph_store` now
  documents the supersession of ADR-082526-3ca6/AC-5's no-bridge fallback
  inline.
- `tests/test_hitl_door.py`, `tests/test_hitl_timeout_cancel.py`,
  `tests/test_attention_projection.py` — develop-side fixtures assumed the
  shipped fallback store; rebound to the explicit
  `services.dag_agents.get_run_store` test seam with an in-memory store, and
  the no-spine 503 tests now re-bind the seam to the production refusal
  (the empty-membership early return #1240 added to `/pending` otherwise
  answers 200 before the store is consulted).

Net -2 collected test nodes in `packages/hive-conductor/backend/tests`
(dropped develop-side duplicates of the fail-closed contract under its
retired semantics); recorded in the `inventory-delta` block above.

Validated at the merge commit `c89c011e6`: full
`packages/hive-conductor/backend/tests` 2772 passed, 6 skipped;
`packages/maistro-core/tests/graph/durable_runs` legacy-archive /
recovery-wakeup / continuation-conformance 96 passed, 14 skipped; ruff check
+ format on the resolved files; `check-merge-markers`,
`check-convergence-matrix`, `check-execution-lifecycles` (19 lifecycles,
3 CANONICAL), `check-wiring-reads`, `check-vulture-baseline` (1414 reviewed
identities, ratchet OK), `check-suite-inventory`.
