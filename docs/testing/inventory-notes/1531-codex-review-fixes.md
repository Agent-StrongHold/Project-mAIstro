---
inventory-delta:
  packages/maistro-canvas/tests: +12
  packages/maistro-core/tests: +15
---
# 1531-codex-review-fixes

Codex review on PR #1531 (Canvas crash-atomic admission, #1055) raised 8
findings; 6 were genuine and fixed, with tests added alongside each fix.

## `packages/maistro-canvas/tests` (+12)

- `test_canonical_execution.py` (+7): a live-leased `RUNNING` receipt is left
  alone by reconciliation even when its canonical Run is momentarily
  `QUEUED`, while an *expired*-lease one is still requeued (finding 4, two
  tests); reconciliation pages past a full first batch of already-healthy
  Canvas admissions to reach a later broken one, and the `admission_source`
  filter keeps a non-Canvas Run in the same status from crowding a page
  (finding 1, two tests); a genuinely concurrent admission race (the durable
  `canvas_job_id` claim's insert losing) adopts the winner instead of
  orphaning a second Run, and does not launder a conflicting retry through
  that recovery path (finding 2, two tests); and a same-key retry naming a
  *different* canvas/layer is rejected once the admission fingerprint
  includes both resource ids (finding 3, one test).
- `test_canonical_executor_integration.py` (+2): a same-key retry of a
  still-active (not yet terminal) operation with a changed prompt is
  rejected the same way a terminal retry already was, instead of depending
  on timing (finding 5); and a terminal retry whose durable receipt already
  exists never calls `admit()` a second time, proven via a stub that raises
  if it is (finding 6).
- `test_routes_idempotency.py` (+3, new file): an explicit
  `"idempotency_key": null` in the request body falls back to the
  `Idempotency-Key` header instead of silently admitting with no operation
  identity (finding 7); a header/body naming genuinely different non-null
  keys is a 422; and a conflicting retry that reaches `admit()` after the
  earlier operation goes terminal is a 409, not a 500 from the global
  exception handler (finding 8).

## `packages/maistro-core/tests` (+15 = 5 new cases × 3 `spine` backend params)

`test_spine_conformance.py` (+5, ×3 for the `memory`/`sqlite`/`postgres`
`spine` fixture -- `postgres` collects but skips without
`MAISTRO_TEST_PG_DSN`, same as every other parametrized case in this file):
the new `canvas_job_id` unique-claim primitive (migration 039, `runs/store.py`,
`runs/sqlite_store.py`) mirrors the existing `schedule_id`/`scheduled_for`
occurrence claim (migration 015) and `delegation_key` claim (migration 037) --
a second `create_run` for the same Canvas job is refused, eight genuinely
concurrent claims (`asyncio.gather`) converge on exactly one winner, a
different job id is unaffected, deleting a Run releases its claim, and --
because `canvas_job_id` is not an exclusively Canvas-owned field name at this
layer -- a non-Canvas Run that happens to carry the same string in its own
provenance does not block a real Canvas admission from claiming it.
