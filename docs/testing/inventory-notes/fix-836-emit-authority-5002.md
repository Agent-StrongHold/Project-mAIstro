---
inventory-delta:
  packages/maistro-core/tests: +6
---

# #836 emit firing-authority regression evidence

`EventBus.emit` previously advanced `fire_count` / `last_fired` and reported a
trigger in the fired list even when no handler was registered for its
`action_type` or the handler raised and the exception was swallowed. #836 moves
the success counters onto the path where a registered handler completed, skips
no-handler matches with a warning, and surfaces handler failures through
`TriggerActionFailure`.

The +6 collected node IDs are all new regression evidence in the new
`TestEmitFiringAuthority` class in `tests/events/test_events.py`; no node ID
was removed:

- **No handler (2):** a matched trigger with no registered handler is not
  counted as fired (and the unmatched `action_type` is warned, not silent),
  and a no-handler delivery does not arm the cooldown, so registering the
  handler later can still fire.
- **Raising handler (3):** a raising handler is excluded from the success
  counters and its original exception is chained through
  `TriggerActionFailure`; a failed attempt does not arm the cooldown, so a
  retry still reaches the handler; and one failing handler neither aborts the
  remaining triggers and subscribers nor corrupts the delivery history.
- **Contract violation (1):** a sync (non-coroutine) handler registered against
  the coroutine handler contract is reported as a failure rather than counted
  as a fired trigger via the old swallow.

The tests that previously pinned the swallow behavior (sync lambdas awaited in
an async path) are rewritten as explicit async handlers/subscribers with no
collected-count change.
