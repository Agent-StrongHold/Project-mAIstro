---
inventory-delta:
  packages/maistro-core/tests: +15
  packages/hive-conductor/backend/tests: +10
---

# #1120: manual schedule fire through the canonical admission spine

Adds five occurrence-identity cases to `test_spine_conformance.py`, each run
against all three Run stores (memory, SQLite, PostgreSQL — hence +15): a
retried manual fire is one occurrence even across different wall-clock
instants (`schedule_fire_id` is the identity, not `datetime.now()`); a manual
token never consumes a nominal `(schedule_id, scheduled_for)` claim (the
`manual:` prefix keeps the identity spaces disjoint); the loser of a manual
race resolves the winner's Run via the new `find_occurrence_run` read half of
the claim; an unclaimed fire has no Run to reconcile; and nominal claims
resolve through the same lookup. Supporting changes: `occurrence_key`
understands manual fires, the SQLite/PostgreSQL claim indexes become
`COALESCE('manual:' || fire_id, scheduled_for)` (migration 034), and
recurring admissions now stamp `schedule_trigger: "recurring"` (asserted in
`test_admission.py`, no new collected cases).

Adds ten cases in the Hive suite's `test_manual_fire_canonical.py`: canonical
Workspace/Project/Run provenance for a manual fire with the legacy
`run_registered_dag` path forbidden; concurrent double submit with one
`fire_id` reconciling to one Run; retry after completion returning the same
receipt without spending a second `max_runs` unit; distinct tokens as
distinct deliberate firings; the recurring enumeration cursor
(`last_fired_at`/`next_due_at`) untouched by a hand fire; template resolution
from the canonical GraphTemplate store with the process-local registry
forbidden; failure before admission recording nothing; exhaustion enforced on
the manual path with the schedule disabled; a real-route, real-Container E2E
driving `POST /v1/schedules/{id}/run` twice with one `Idempotency-Key` and
asserting one Run consumed to a completed NodeRun and Attempt; and the
standalone no-Container fallback still reachable only through the same
`_canonical_admitter` gate the recurring loop uses.
