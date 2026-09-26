---
inventory-delta:
  packages/maistro-core/tests: +50
---
# claude-ws-1182-enforce-root-run-concurrency-ceilings-cb08

The +50 are all new (#1182). No existing test was removed or renamed.

- `tests/runs/test_run_concurrency_limits.py` adds 46 node IDs. Most are
  parametrized over the memory, SQLite and PostgreSQL backends. They cover:
  the principal and Workspace ceilings, child Runs holding no slot, each
  parked or terminal status freeing a slot, resume not counting as
  admission, fairness across principals and Workspaces, concurrent
  admission, tightened limits, and the spine-wiring path that reads settings.
- `tests/security/test_resource_policy_declared_floors.py` adds 4. Two are
  weakening mutants for the new floors. The other two show that each new
  floor can be tightened but only loosened with the unsafe override.

The backlog fixtures in `test_fair_scan_parity.py` and
`test_cross_store_crash_reconciliation.py` now construct their stores with
room above the ceiling. Their node IDs are unchanged.
