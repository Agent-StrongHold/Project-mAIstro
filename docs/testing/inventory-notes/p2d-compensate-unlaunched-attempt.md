---
inventory-delta:
  packages/maistro-core/tests: +8
---

# P2d: owned CREATED prelaunch compensation (#2369 / #232)

Adds `compensate_unlaunched_attempt` (lifecycle construction + RunStore
locked write on in-memory / SQLite / PostgreSQL) and wires
`AttemptExecutionService._terminalize_if_open` so non-requested CREATED
failures commit CANCELLED+RECOVERED under the fence. Requested
CancelledError stays on the ordinary CANCELLED path (not stamped
RECOVERED). RUNNING / terminal / stale-fence winners refuse.

## Collected node IDs

`packages/maistro-core/tests/runs/test_compensate_unlaunched_attempt.py` (+8):

- construction: CREATED → CANCELLED+RECOVERED; RUNNING / started_at /
  already-cancelled refusals
- store: persist under matching fence; stale fence; RUNNING winner; missing id
