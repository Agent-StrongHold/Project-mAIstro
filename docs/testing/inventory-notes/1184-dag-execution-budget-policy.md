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

## Repair round (develop merge 4df9dd9bd, head 82d75cc4e)

Resolving the develop merge into this branch surfaced one code conflict in
`legacy_dag_node._run_llm_node` between this issue's declared-timeout transport
and develop's #718 governed-invocation cutover. Resolution keeps both
authorities without letting either weaken the other: when a canonical Attempt
exists, the governed `dag_node_completion` path runs and the durable walker
owns the deadline (`attempt_executor` persists `deadline_at` and terminalizes
`TIMED_OUT`); the compatibility fallback keeps the declared,
policy-resolved transport timeout. A hard-coded product-runner timeout still
cannot extend work past the canonical deadline on either path.

Post-merge validation: `uv run ruff check .` clean; `uv run ruff format
--check .` clean; `uv run pytest packages/maistro-core/tests/graph
packages/hive-conductor/backend/tests/test_canonical_dag_runner.py
packages/hive-conductor/backend/tests/test_edit_lock_and_audit.py
packages/hive-conductor/backend/tests/test_legacy_dag_governed_quota.py -q`
→ 1542 passed, 112 skipped; declared-budgets + seeds suite → 25 passed;
`scripts/check-suite-inventory.py` green for both suites;
`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
--exclude '*/third_party/*'` → exit 0, unclassified 0 (the security-gate
failure at the pre-merge head was the stale ledger against a moved develop
base; the merge's ledger state covers all 1371 identities).
