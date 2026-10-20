---
inventory-delta:
  packages/maistro-core/tests: +7
  packages/hive-conductor/backend/tests: +3
---

# #1120 repair: cover the manual-fire paths the diff-coverage floor named

Follow-up to `1120-manual-fire-canonical-occurrence.md`, from the branch's own
CI evidence: the Coverage gate (publish-set floor + diff coverage) failed on
five files whose branch-added lines no collected test executed — the manual
fire's duplicate-claim reconciliation body and recovery error paths in
`maistro/scheduling/admission.py`, the `find_occurrence_run` "no occurrence
in provenance" arc in all three Run stores, and the `fire_id`
strip-and-bound refusal arcs in the Hive route — and the same repair shrank
`_admit_manual` out of the un-baselined radon C-block it had grown into and
removed the `PendingFire` model validator that doubled an un-banked vulture
identity. Tests added, no production behavior changed:

`packages/maistro-core/tests` (+7, `tests/scheduling/test_admission.py` and
`tests/runs/test_spine_conformance.py`) — four cases in `TestManualFire`: a
loser whose probe missed the winner's claim (the insert refused anyway)
reconciles to the winner's Run with its marker released unspent; a duplicate
claim whose winner cannot be resolved still reports `already_fired` with no
Run to name; recovery survives a run store that cannot answer the stale
marker's probe (warning, marker deferred, the fire still goes out); and
recovery survives a schedule store that refuses the settle write (same
degradation, next admission retries). Plus `find_occurrence_run` called with
provenance carrying no occurrence claim at all (`{}` and `None`) answering
`None` on memory, SQLite, and PostgreSQL — hence one test × 3 backends.

`packages/hive-conductor/backend/tests` (+3, `test_schedule_manual_fire_canonical.py`)
— the real route refuses a blank body `fire_id` (one occurrence identity
shared by every blank request, if accepted), an overlong body `fire_id`
(unbounded data into durable provenance), and an overlong `Idempotency-Key`
header (the header is held to the body's contract), each with 422 and no Run
created.
