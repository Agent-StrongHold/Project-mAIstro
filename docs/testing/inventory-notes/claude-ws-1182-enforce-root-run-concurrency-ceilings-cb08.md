---
inventory-delta:
  packages/maistro-core/tests: +58
  packages/maistro-server/tests: +1
---
# claude-ws-1182-enforce-root-run-concurrency-ceilings-cb08

All 59 new node IDs are for #1182: 58 in core and 1 in maistro-server. No existing test was removed or renamed.

- `tests/runs/test_run_concurrency_limits.py` adds 54 node IDs. Most are
  parametrized over the memory, SQLite and PostgreSQL backends. They cover:
  the principal and Workspace ceilings, child Runs holding no slot, each
  parked or terminal status freeing a slot, resume not counting as
  admission, fairness across principals and Workspaces, concurrent
  admission, tightened limits, and the spine-wiring path that reads settings.
  They also cover review regressions:
  - a duplicate occurrence at the ceiling is still refused as a duplicate;
  - a refused occurrence is admissible once a slot frees;
  - a SQLite refusal leaves a sibling store's open write intact;
  - `Container` chat admission re-raises the refusal.
- `tests/security/test_resource_policy_declared_floors.py` adds 4. Two are
  weakening mutants for the new floors. The other two show that each new
  floor can be tightened but only loosened with the unsafe override.

The backlog fixtures in `test_fair_scan_parity.py` and
`test_cross_store_crash_reconciliation.py` now construct their stores with
room above the ceiling. Their node IDs are unchanged.

- maistro-server `tests/api/test_chat_completions_gate.py` adds 1 node ID. It
  checks that a chat turn over the Workspace ceiling gets a 429 with
  `Retry-After` and is never routed.
