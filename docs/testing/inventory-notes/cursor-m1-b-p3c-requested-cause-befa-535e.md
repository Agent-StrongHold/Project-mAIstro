---
inventory-delta:
  packages/maistro-core/tests: +6
---

# P3c: REQUESTED cancellation_cause on transition_attempt (#2421 / #232)

Teaches generic `transition_attempt` to accept only `None` or `REQUESTED`
(never `RECOVERED`) and only with target `CANCELLED`. Wires
`governed_model.settle_operation_identity` so authorization-refused
`outcome="cancelled"` persists REQUESTED. Hive-conductor assertions extend
an existing settle test (no new collected node ID).

## Collected node IDs

`packages/maistro-core/tests/runs/test_transition_attempt_requested_cause.py` (+6):

- construction: REQUESTED stamps; unset default; RECOVERED refuse; non-CANCELLED refuse (+4)
- in-memory store: persist REQUESTED; refuse RECOVERED (+2)
