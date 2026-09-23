---
inventory-delta:
  packages/maistro-core/tests: +18
  packages/hive-conductor/backend/tests: +12
---

# #1120: manual schedule fire through the canonical admission spine

Adds five occurrence-identity cases to `test_spine_conformance.py`, each run
against all three Run stores (memory, SQLite, PostgreSQL — hence +15), plus a
legacy SQLite schema-upgrade case in `test_sqlite_store.py`: a
retried manual fire is one occurrence even across different wall-clock
instants (`schedule_fire_id` is the identity, not `datetime.now()`); a manual
token never consumes a nominal `(schedule_id, scheduled_for)` claim (the
`manual:` prefix keeps the identity spaces disjoint); the loser of a manual
race resolves the winner's Run via the new `find_occurrence_run` read half of
the claim; an unclaimed fire has no Run to reconcile; and nominal claims
resolve through the same lookup. Supporting changes: `occurrence_key`
understands manual fires, the SQLite/PostgreSQL claim indexes become
`COALESCE('manual:' || fire_id, scheduled_for)` (migration 042 — renumbered
after each develop collision: 034→039→042, finally re-parented onto
develop's `036_audit_log_org_scope` tip), and recurring admissions now
stamp `schedule_trigger: "recurring"` (asserted in `test_admission.py`, no
new collected cases).

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

## Merge reconciliation with develop's #1119 spine (2026-09-12)

Merging `origin/develop` (which shipped its own canonical manual-fire
implementation via `admit_due(manual=True)`) onto this branch reconciled the
two designs: develop's admitter spine (atomic `reserve_fire`/`settle_fire`
quota, fail-closed `ScheduleAdmissionUnavailable`, request correlation,
consumer-tick execution) kept as the authority, with this branch's occurrence
identity ported into it — `admit_due(..., manual=True, fire_id=...)` claims
`(schedule_id, 'manual:' + fire_id)`, and a duplicate claim returns
`ScheduleAdmission.reconciled_run_id` (the winner's receipt) instead of a
bare refusal. No test-count changes from the reconciliation itself; two
existing develop assertions were updated to the reconciled contract:
`test_admission.py::test_a_claimed_occurrence_is_reported_not_recreated` now
races on one `fire_id` token (the instant was never the identity #1120
required) and asserts the reconciliation, and
`test_schedule_manual_fire_canonical.py`'s route E2E asserts the Run is
consumed to `COMPLETED` by the manual fire's prompt consumer tick rather than
left `QUEUED` for the 30s recurring tick.

## Second repair pass: the claim answers before any refusal (2026-09-23)

Two edges surfaced by re-validating the merged head against reachable
behavior, both reproduced before repair. First, a retry carrying the same
`fire_id` after the winner's fire spent the last `max_runs` unit was refused
("has used all 1 of its runs") instead of reconciling — telling a retried
caller the fire failed when its Run demonstrably exists. `admit_due(manual=True)`
now probes the occurrence claim *before* any refusal (exhaustion snapshot,
`reserve_fire`, template resolution), so a caller-stable token whose Run
exists always reconciles; `_fire_manual_canonical`'s own `exhausted`
pre-check was removed as a stale-ordered duplicate of the admitter's, and its
reconciliation branch reads the durable row for the disable so a retry's
Hive-row projection cannot report a schedule the store has already disabled.
Second, the `Idempotency-Key` header — the route's documented retry identity —
bypassed the body's `fire_id` contract: a 5,000-character header flowed
verbatim into durable Run provenance (reproduced). The header is now held to
the same stripped/bounded contract (`_check_fire_id`), with a blank header
behaving as an absent one. Coverage: `test_admission.py` gains the
retry-after-exhaustion and retry-after-template-deletion reconciliations
(+2); the Hive suite gains the service-level retry-after-exhaustion receipt
and the route-level idempotency-key contract test (stripped keys reconcile
to one Run; an over-long key is a 422 before any durable write) (+2).

## Third repair pass: merge with develop 84d937add (2026-09-23)

Develop's #1531/#1079/#1395 took the alembic ids this branch had claimed
(`039`, then the `040` parent, then the `036_audit_log_org_scope` tip), so the
manual-fire occurrence migration renumbered 039→041→042 and re-parented onto
develop's chain tip `036_audit_log_org_scope` — the same reconciliation that
revision's own docstring records. `tests/migrations/test_audit_scope_migration.py::test_audit_scope_migration_is_the_single_head`
pinned the audit migration AS the tip; it now asserts the same contract the
way it survives any later migration: exactly one head, with the audit scope
migration on that head's chain. No collected-test counts changed this pass
(96 migration tests, 1322 core runs+scheduling on PG legs, 2577 Hive backend
— the deltas over the prior pass are develop's own new suites).
