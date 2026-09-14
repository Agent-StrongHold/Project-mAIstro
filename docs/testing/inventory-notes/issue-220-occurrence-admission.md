---
inventory-delta:
  packages/maistro-core/tests: +4
---
# Issue 220 occurrence admission

Adds the missing live PostgreSQL race evidence for two independent
`ScheduleRunAdmitter` instances sharing a due window, plus a conformance test
that keeps `max_runs` disabled when serialized admissions reach the limit from
stale ticker snapshots. The store-side exhaustion check is required because a
caller-level `disable` decision cannot account for another ticker's admitted
fires.
