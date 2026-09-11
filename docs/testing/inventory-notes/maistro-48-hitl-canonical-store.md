---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# maistro-48-hitl-canonical-store

The HITL repair adds wiring regression coverage in `test_dag_agents.py` and
`test_hitl_timeout_cancel.py` proving that a Conductor without a canonical
spine cannot obtain or expose a HITL store. Existing route tests bind their
document-shaped fixture explicitly to the new canonical-store seam, so they no
longer assert that the production route uses `InMemoryDurableRunStore`.
