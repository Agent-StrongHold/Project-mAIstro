---
inventory-delta:
  packages/maistro-core/tests: +15
  packages/hive-conductor/backend/tests: +8
---
# Issue #1184 declared DAG execution budgets

Makes `DAGFile.max_cycles` and per-node `timeout_s` authoritative inputs to the
canonical executor instead of fields execution ignored, per
ADR-100126-b118.

## New tests

`packages/maistro-core/tests/graph/durable_runs/test_declared_budgets.py`
(+15) pins the bounded policy (`maistro.graph.policies`) and the durable
walker's enforcement:

- clamp envelopes and the unreadable-declaration rules for cycles (tightest
  cap) and timeouts (incumbent default);
- a declared `max_cycles` bounds traversal waves, fails `CycleBudgetExhausted`
  naming the budget when exhausted, and changing the value changes how much
  loop work runs;
- a budget covering the DAG's depth completes it; a shallower one fails
  closed naming the shortfall; an undeclared budget leaves the step floor as
  the only bound;
- a declared node `timeout_s` becomes the canonical ExecutionRuntime deadline
  (Attempt `TIMED_OUT` with `deadline_at`, well inside the retired 120s
  constant), changing the value changes whether work survives, out-of-envelope
  values clamp to the ceiling, and undeclared nodes keep the no-deadline
  behavior.

`packages/hive-conductor/backend/tests/test_canonical_dag_runner.py` (+8)
proves the product path end to end: declared `max_cycles` enforced and
reported (projection + Run provenance + durable cycle counter), clamped
out-of-policy values recorded declared/effective, undeclared budgets absent, a
declared node timeout enforced by the runtime against a slow LLM (the
hard-coded 120s constant no longer governs), the value change flipping the
outcome, timeout clamping with per-node provenance, and the update route
refusing out-of-envelope `max_cycles` writes.

## Data migration riding the same change

`packages/maistro-core/src/maistro/graph/seeds/daily_status.py` declares
`max_cycles: 5` for its five-wave depth (was the inert `1`);
`test_daily_status_seed_has_required_identity_fields` pins the migrated value
(count unchanged).
