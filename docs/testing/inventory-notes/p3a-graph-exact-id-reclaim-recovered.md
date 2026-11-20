---
inventory-delta:
  packages/maistro-core/tests: +2
---

# P3a: Graph exact-ID reclaim persists RECOVERED (#2366 / #232)

`DurableRunExecutionStore._settle_one_canonically` now calls
`RunStore.reclaim_expired_attempt` instead of reconstructing via
`reclaim_attempt` + generic `transition_attempt` (which dropped the cause).
Terminal CANCELLED winners still report as reclaimed; COMPLETED/live do not.
Requested/unknown CANCELLED is never rewritten to RECOVERED.

## Collected node IDs

`packages/maistro-core/tests/graph/durable_runs/test_canonical_execution_store.py`
(+2):

- Graph reclaim persists CANCELLED+RECOVERED on the canonical row
- Requested CANCELLED winner is not relabeled RECOVERED

Existing reclaim / race tests assert the persisted cause where they already
cover settlement.
