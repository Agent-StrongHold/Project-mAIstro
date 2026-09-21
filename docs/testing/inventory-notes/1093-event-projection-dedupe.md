---
inventory-delta:
  packages/maistro-core/tests: +6
---
# 1093-event-projection-dedupe

Six new tests, all additions, no removals or compensating changes:

- `tests/events/test_event_projection_dedupe.py` (5): legacy projection
  rejects stores without atomic-append disposition; in-memory dedupe
  semantics for event projection (#1092).
- `tests/events/test_pg_event_projection_dedupe.py` (1): the PG-leg twin,
  skipped without `MAISTRO_TEST_PG_DSN` but still collected.

Verified +6 = collected (9456) vs recorded (9450); every suite besides
`packages/maistro-core/tests` unchanged.
