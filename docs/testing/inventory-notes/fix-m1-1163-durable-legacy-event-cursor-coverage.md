---
inventory-delta:
  packages/maistro-core/tests: +1
---
# fix-m1-1163-durable-legacy-event-cursor-coverage

Answers a CI `Coverage gate (publish-set floor + diff coverage)` failure on
`fix-m1-1163-durable-legacy-event-cursor`'s first push: `container.py`'s new
`if new_cursor > lease.position:` branch (`process_durable_events`, #1163)
only ever had its truthy side exercised -- every existing test appends at
least one event before ticking, so the store's `advance()` is always
called and the false arm (nothing new settled this round) was never hit,
landing diff coverage at 75% of 4 changed branch arcs against an 80% floor.

`test_a_tick_with_nothing_new_does_not_advance_the_stored_cursor` (+1,
`tests/test_container_wiring.py`) ticks a freshly-wired container with an
empty `durable_event_log` and asserts the returned/cached cursor is 0, then
claims the lease again and asserts the durably stored position is still 0
-- proving `advance()` was never called, not just that nothing visibly
changed.

Verified with `coverage run --branch` that `container.py`'s
`process_durable_events` (lines ~705-750, cursor claim/advance path) has no
remaining missing lines or partial branches. Full
`packages/maistro-core/tests/test_container_wiring.py` +
`tests/events/` (348 passed, 51 skipped) pass. `ruff check`/`ruff format
--check` clean.
