---
inventory-delta:
  packages/maistro-core/tests: +5
---
# cursor-m1-b-p5a-recovered-rediscovery-8551-a8d1

Develop-sync merge of `origin/develop` (`33ac30c5f1`, the P4b/#2425 squash)
into the P5a rediscovery branch. P4b's test content largely already existed
on this branch (absorbed pre-restack, byte-identical), so the merge adds
only the two pieces the branch had never carried — all in
`packages/maistro-core/tests`:

- `test_recover_orphaned_attempt.py::TestRecoverOrphanedPgWriter`
  (**+3**) — the no-services PG-writer pins P4b added on develop: happy
  CANCELLED+RECOVERED write under the owning Run, missing-attempt
  `AttemptNotFound`, and wrong-owner `RunIntegrityError`, each asserting the
  parent locks only read (`pool.updates == []` on the refusal arms).
- `test_recovery_completion_budget.py::test_sweep_catches_recovered_
  disposition_refused` (**+2**, memory/postgres spine legs) — the sweep's
  `RecoveredDispositionRefused` catch pinned on develop; the same catch this
  branch's P5a replay loop pins from the other side.

Correction (repair round): "No test was removed or renamed" was wrong as
originally written. The merge resolution dropped one test develop carries
inside the same conflicted block — `test_local_recovered_disposition_happy_path_parks_record`
from the P4b squash — and a follow-up commit restores it byte-for-byte from
`33ac30c5f1`, with its own note and delta
(`m1-232-p5a-restore-local-recovered-happy-path.md`, `+1`). The branch's own
P5a additions (rediscovery file, leaseless-orphan writer tests, gate/refusal
pins) were already counted by prior notes on this branch, so their deltas do
not re-apply here.
