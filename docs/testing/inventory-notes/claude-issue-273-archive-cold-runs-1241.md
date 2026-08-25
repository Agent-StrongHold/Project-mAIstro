---
inventory-delta:
  packages/maistro-core/tests: +10
---
# claude-issue-273-archive-cold-runs

Ten new node IDs, all in `packages/maistro-core/tests/runs/test_archive_sweep.py`.
Nothing removed or reparametrised.

The one that carries the design is
`test_a_run_with_a_deletion_date_is_never_archived`. It is the test that fails
if anyone hooks archiving into `purge_expired_runs`, which is the natural
implementation and the one ADR-082226-f436 decision 2 forbids — "archiving is
not a way to avoid deciding that". Its Run is cold by every other measure; what
disqualifies it is that somebody chose a date to delete it on.

The rest: the tier is off without an archive store (decision 9); a cold Run
kept indefinitely is archived; recent Runs and live work are not; the archived
bytes round-trip to the Run rather than merely existing; a read after archiving
still returns the record (decision 6 — a silent None is indistinguishable from
deletion by every caller); the batch limit holds and a non-positive one is
refused; and the horizon is a parameter, since open question 1 declined to
freeze a number.

Against a real `FilesystemArchiveStore`, not a fake. The sweep's job is to put
bytes somewhere they can be read back, and a fake that records calls proves
only that the call was made with arguments the test already knew.
