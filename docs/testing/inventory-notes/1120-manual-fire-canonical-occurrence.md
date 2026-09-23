---
inventory-delta:
  packages/maistro-core/tests: +31
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
## Sixth pass: the crash window holds, it does not spend (2026-09-23)

The finding this pass repairs: `reserve_fire` durably counted the run and
disabled on exhaustion *before* any Run existed, so a process that died
between the reservation and the Run insert left the durable row claiming a
firing that never happened — reproduced on a fresh SQLite store (restart
preserved `runs_so_far=1`, `enabled=False`, `last_run_id=None`): a
`max_runs=1` schedule was bricked, no Run, no retry possible. The claim is
now a durable `PendingFire` marker naming the fire's token: it holds the
slot (every exhaustion check counts held markers, so the #1119 last-run race
stays closed) but spends nothing — `runs_so_far`, `enabled`, and the cursors
move only in `settle_pending_fire`, the one write that also removes the
marker and links the Run. A holder that dies mid-window leaves the marker
for recovery (`_reconcile_pending_fires`, lease-gated by
`_PENDING_FIRE_LEASE` so a live fire is never touched): a Run for its token
confirms the spend, no Run releases the slot. The in-memory
`FireReservation` type is gone; `reserve_fire`/`settle_pending_fire` are the
two store methods, both implementations (in-memory, PostgreSQL) share
`_reserve`/`_settle_pending` so they cannot drift.

Coverage (+13 `packages/maistro-core/tests`): `test_store.py` rewrites the
reservation cases to the hold/settle contract — a hold does not spend, the
held slot counts until settled, a release leaves no trace, a confirmation
spends and disables on exhaustion, settling without a marker answers None,
the marker survives the payload round trip (+9 across the three store
backends), plus an executed fresh-SQLite crash-window reproduction: kill
between reserve and Run, restart, nothing spent (+1). `test_admission.py`
gains the crash window end to end — a crashed fire leaves no firing and its
retry fires, the recurring tick releases a stale marker before firing what
is owed, and a fresh (in-lease) marker is untouchable by tick and rival fire
alike (+3); the failure-after-Run case is rewritten to assert the row stays
unspent until recovery confirms it from the Run itself. Hive-side behavior
is unchanged by this pass (its suite still collects 2578): the admitter's
contract shift is invisible to the route and service, which keep reading
`ScheduleAdmission`.

Also in this pass: `scheduler.py`'s committed text had picked up CRLF line
terminators (the merge at `d60bc7fd6`) and the handoff note a trailing
space — normalized back to LF; no content change.

## Independent verification pass at 5e75e7e9 (2026-09-23)

Re-executed at the exact head. Driver checks all pass (uv sync, ruff
check/format, core 421 passed/147 skipped, Hive 100 passed, both suite
inventories). Independently re-run: radon gate EXIT=0 (70/70 blocks — the
prior un-baselined `_admit_manual` C-block is gone via decomposition);
convergence-matrix checker EXIT=0; ruff check clean. The vulture gate still
exits 1 (1430 findings vs 1415 reviewed), reproduced on a git-archive scratch
tree of base 8bb344e32 with a byte-identical findings multiset after
line-number normalization (1430=1430, no added/removed identities) — the
failure is the upstream ledger's staleness, not branch debt. PG legs re-run
on a fresh disposable pg18 container (`MAISTRO_TEST_PG_DSN`) after
`alembic upgrade head` through the full chain ending at single head 042:
544 core runs/scheduling tests and 29 migration tests pass; migration tests
and core suites also pass without a DSN (PG params skip). Adjacent Hive
route-consumer suites (scheduler-canonical-admission, scope-coverage,
registered-dag-recovery, evolution-service, platform) 127 passed. Acceptance
re-derived from the issue: configured `fire_now` admits through
`ScheduleRunAdmitter.admit_due(manual=True, fire_id=...)` (canonical
Workspace/Project via `_canonical_scope`, fail-closed
`ScheduleAdmissionUnavailable` instead of the compatibility path, which now
requires no Container at all); occurrence identity is
`(schedule_id, 'manual:' + fire_id)` with the `manual:` prefix keeping
identity spaces disjoint; route double submit on one `Idempotency-Key`
reconciles to one Run (E2E asserts canonical scope, `schedule_trigger` manual
vs recurring provenance, durable template, prompt consumption to a completed
NodeRun+Attempt, one count against `max_runs`); pending-fire markers hold
without spending so a pre-Run crash claims nothing and a post-admission crash
recovers via `_reconcile_pending_fires`. No premature closure keywords in the
PR body or commit messages (references only). No issues remain open on this
verifier's list.
