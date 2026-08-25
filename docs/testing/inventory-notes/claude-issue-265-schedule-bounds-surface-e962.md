---
inventory-delta:
  packages/hive-conductor/backend/tests: +22
---
# claude-issue-265-schedule-bounds-surface-e962

All 22 are additions to `packages/hive-conductor/backend/tests/test_scheduler.py`
(24 -> 46). Nothing was removed, renamed or reparametrised, so the net is also
the gross — there is no compensating change hiding inside it.

They cover #265 in four groups:

- **Projection (4).** The definition takes its zone and bound from the row; a
  row predating the columns still projects to UTC/unbounded; a disabled row
  projects as disabled; a non-UTC zone changes the *instant* a schedule fires,
  not just its label.
- **Exhaustion (3).** A bounded schedule fires its bound and then disables; the
  disable is not resurrected by the next tick's `store.put(...)`; `last_run_id`
  on the row resolves to the Run that claimed the occurrence.
- **Manual fire (5).** `fire_now` creates a Run and counts it; a fire that
  cannot start leaves no stamp; the bound applies to manual fires; a targetless
  or unknown schedule is refused.
- **HTTP surface (10, of which 4 are one parametrised case).** Create with and
  without the new fields, update them, and reject an unusable zone or bound at
  the boundary with a 422 rather than a tick that raises forever. The manual-run
  endpoint returns 409 without stamping, and 404 for an unknown schedule.
