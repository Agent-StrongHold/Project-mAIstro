---
inventory-delta:
  packages/hive-conductor/backend/tests: +15
---
# Issue #35 / #1036: projection lifecycle metadata is mirrored, never invented

Fifteen collected test node IDs (thirteen functions; the non-terminal
mirror case is parametrized over all five canonical non-terminal states) in
`packages/hive-conductor/backend/tests/test_dag_run_projection_lifecycle.py`
close the #1036 closure-safety finding under issue #35's census: a canonical
Run that parks non-terminal (WAITING for a human answer, PAUSED, QUEUED,
RUNNING, CREATED) reaches the Conductor projection writer through the run
route's failure branch — the canonical facade raises for anything not
`completed` — and the writer passed that intermediate status to
`finish_run`, which stamps `finished_at` once and refuses every later
update. A Run the spine had not finished was irreversibly presented as
finished, and a stale terminal row kept its locally stamped finish time over
whatever the spine later decided.

Write side (the projection writers and the shared
`DagRunStore.record_outcome` terminality contract): the run-route writer
fail-closes on input outside the canonical vocabulary — no row, no finish,
nothing fabricated (#1877) — and finishes only terminal canonical outcomes,
so a parked Run's row stays open and correlated with no invented
`finished_at`; the chat workflow writer records the canonical outcome under
the shared #1036 contract, so a non-terminal canonical state is mirrored
open with the canonical correlation and no invented `finished_at`; all four
terminal statuses finish normally at both writers; a late non-terminal
mirror cannot unfinish a finished receipt; and an end-to-end
`POST /v1/dags/{id}/run` test drives the real failure branch for a parked
Run. Open rows survive persist/reopen exactly.

The #1036 required regression — record WAITING, resume after recovery to
COMPLETED, prove the projection was never irreversibly finished at the
intermediate state — is pinned end to end, including that the terminal write
still lands on the open row.

Read side (`services.dag_run_inspection`): lifecycle reconciliation now
replaces status AND finish time, including null — a terminal row over a
canonical Run the spine holds open serves the open lifecycle in list and
detail; the served finish time is the canonical Run's own `finished_at`
(datetime → the existing epoch-seconds wire shape), never the projection's
write clock; and the absent-canonical fallback still serves the recorded
receipt untouched, proving no historical record is rewritten.

Red/green evidence: the suite was written first and failed 11 of 13 at the
implementation base (the two passing cases pin pre-existing correct
behavior: terminal finishes and absent-canonical fallback); after the fix,
and after the same terminality contract was extended to the chat writer
two more cases were added for it, all 15 pass. The branch was then rebuilt
onto a newer `develop` that had independently merged the #1877 writer and
overlay work; the writer pins were adapted to that merged semantics (the
route writer fail-closes before opening a row on malformed input; the
read-side overlay carries displayed lifecycle truth), the read-side pins
were re-pointed at the merged scoped-reader seam, and all 15 still pass
alongside the 12 authority tests, with the full hive-conductor backend
suite (3971 passed, 26 skipped) and `ruff check` / `ruff format --check`
green at the rebuilt head.
