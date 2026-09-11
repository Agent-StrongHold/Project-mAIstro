---
inventory-delta:
  packages/hive-conductor/backend/tests: +8
  packages/maistro-core/tests: +6
---
# 1119-manual-fire-canonical-admission

**+14 across two suites** — the manual schedule fire (`POST /v1/schedules/{id}/run`)
moved onto the canonical `ScheduleRunAdmitter` authority (#1119), and every
behavior the migration promised got its own test.

`packages/maistro-core/tests` (+6, `tests/scheduling/test_admission.py`,
`TestManualFire`) — `admit_manual` is the explicit manual-occurrence variant of
`admit_due`: one Run carrying `admission_source`/`schedule_id`/`scheduled_for`
provenance with QUEUED in the same insert, the cursor advancing only after the
Run exists, `max_runs` binding manual fires and disabling in the same write,
exhaustion and an unresolvable durable template refusing with the schedule byte
for byte unchanged, a failed Run creation leaving no cursor movement, and a
duplicate claim (two fires racing on one instant) reported as `already_fired`
rather than recreated.

`packages/hive-conductor/backend/tests` (+8):

- `test_scheduler.py` (+5) — with a Container present, `fire_now` enters
  `ScheduleRunAdmitter.admit_manual` through the real scope resolution (real
  Workspace/Root Project; the compatibility registry is asserted unread), primes
  the durable template from the registry exactly as a tick would, refuses with
  the product refusal and untouched state when no durable template resolves,
  fails closed (`ScheduleAdmissionUnavailable`) instead of degrading when a
  configured Container is missing a collaborator, and spends `max_runs` on the
  canonical cursor with the disable reaching both definitions. The no-Container
  compatibility tests are unchanged and still pass — the fallback now exists
  only where no Container exists at all.
- `test_schedule_manual_fire_canonical.py` (+3, new file) — the E2E leg the
  acceptance requires: the HTTP route driven over `TestClient` with a real
  `create_container` Container swapped onto the engine port. Asserts the Run
  lives in the Container's run store under the configured Workspace and its
  canonical Root Project (never `hive:schedule:{id}`), actor/principal and
  schedule provenance on the Run, `last_run_id` resolving to it, exactly one
  canonical Run per accepted request, the 409-no-stamp refusal on an
  unresolvable template, and a 503 (not a silent fallback) on a half-wired
  Container.

The full-surface guard `test_a_manual_run_that_cannot_fire_is_a_conflict_not_a_stamp`
still drives the route and still passes: refusing is unchanged, what changed is
that an accepted request is now one canonical Run.
