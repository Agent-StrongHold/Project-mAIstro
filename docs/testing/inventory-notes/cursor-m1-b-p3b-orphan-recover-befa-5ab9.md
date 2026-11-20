---
inventory-delta:
  packages/maistro-core/tests: +32
---

# P3b: Graph orphan recover_orphaned_attempt (#2417 / #232)

Adds `recover_orphaned_attempt` (lifecycle construction + RunStore locked
write on in-memory / SQLite / PostgreSQL) and wires
`attempt_executor._reconcile_orphaned_attempts` onto that seam so leaseless
active Attempts commit CANCELLED+RECOVERED under explicit owning-run resume.
Already-CANCELLED+RECOVERED rows are replayed through the reconciler before
retry. Live leased rows remain refused; the sweep stays on reclaim.

## Collected node IDs

`packages/maistro-core/tests/runs/test_recover_orphaned_attempt.py` (+21):

- construction: leaseless CREATED/RUNNING → CANCELLED+RECOVERED; leased /
  terminal / already-caused refusals (+5)
- in-memory store: persist under owning run; wrong run; leased; missing (+4)
- spine (memory/sqlite/postgres ×4): persist; wrong run; leased; missing (+12)

`packages/maistro-core/tests/graph/durable_runs/test_canonical_execution_store.py` (+4):

- recover mirrors CANCELLED+RECOVERED onto the projection; wrong owning run
- local-mode recover commits RECOVERED; local-mode wrong owning run refuses

`packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py` (+2):

- already-CANCELLED+RECOVERED Attempt is replayed before retry
- superseded recovered Attempt is not replayed onto a QUEUED NodeRun
