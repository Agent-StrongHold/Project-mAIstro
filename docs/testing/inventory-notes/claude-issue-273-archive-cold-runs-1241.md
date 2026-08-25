---
inventory-delta:
  packages/maistro-core/tests: +51
---
# claude-issue-273-archive-cold-runs

Fifty-one new node IDs across three files, split by what they hold. Nothing
removed or reparametrised.

`test_archive_conformance.py` contributes 26 rather than 13 because its
`archive_spine` fixture is parametrised over two backends. The PostgreSQL leg
skips without `MAISTRO_TEST_PG_DSN` — so it is 13 tests locally and 26 in CI,
and the inventory counts node IDs rather than outcomes.

## `test_archive_sweep.py` — the predicate (12)

Which Runs are eligible. The one that carries the design is
`test_a_run_with_a_deletion_date_is_never_archived`. It is the test that fails
if anyone hooks archiving into `purge_expired_runs`, which is the natural
implementation and the one ADR-082226-f436 decision 2 forbids — "archiving is
not a way to avoid deciding that". Its Run is cold by every other measure; what
disqualifies it is that somebody chose a date to delete it on.

The rest: the tier is off without an archive store (decision 9); a cold Run
kept indefinitely is archived; recent Runs and live work are not; a terminal
Run with no finish time is refused rather than compared against `None`; the
archived bytes round-trip to the Run rather than merely existing; a read after
archiving still returns the record (decision 6 — a silent None is
indistinguishable from deletion by every caller); a Run already archived is not
archived again; the batch limit holds and a non-positive one is refused; and
the horizon is a parameter, since open question 1 declined to freeze a number.

Against a real `FilesystemArchiveStore`, not a fake. The sweep's job is to put
bytes somewhere they can be read back, and a fake that records calls proves
only that the call was made with arguments the test already knew.

## `test_archive_sweeper.py` — the driver (13)

What makes the sweep run, and what stops it. Two of these are load-bearing:

`test_admitting_a_chat_turn_drives_the_sweep` is the one that keeps the sweep
out of the vulture ledger. Before it, `archive_cold_runs` was reachable only
from its own tests — the "wired but never read" shape #236 exists to gate, and
the exact defect this issue was filed to remove from `archive_store`. The fix
was a production caller, not a banked ledger entry.

`test_a_chat_turns_own_run_is_never_the_one_archived` states the asymmetry the
seam depends on: admission is the *clock*, not the subject. A chat Run carries
a retention deadline, so it is purge-eligible and therefore never
archive-eligible (decision 10). Its horizon here is one microsecond, so if the
disjointness ever breaks the turn follows itself into the bucket.

The rest: the default policy archives nothing, from the sweeper and through the
admitter both; a named horizon turns it on; a store with no archive tier is
inert rather than an error; a failing archive is swallowed, because an
unreachable bucket must not become a refused chat turn; the throttle skips a
second sweep inside the interval and a zero interval opts out of it; two
concurrent sweeps produce one scan; and the three policy validations refuse a
zero horizon, a negative interval and a non-positive batch.

## `test_archive_conformance.py` — both backends (26)

The in-memory store keeps the Run resident after archiving; it is the reference
implementation of the *protocol*, not a tier that saves bytes. So the half that
can actually fail is untested until PostgreSQL runs it: there the payload column
really is set to NULL, and everything downstream of a read has to keep working.

`test_a_read_after_archiving_still_returns_the_run` is the one that would have
caught the obvious bug. Without read-through in `_payload`, `get_run` returns
None for an archived Run — decision 6's forbidden case, and data loss at the API
boundary rather than a cost optimisation.

The rest: identity and scope outlive the payload, so foreign keys still resolve
and the Project still knows it owns Runs; the NodeRuns and Attempts under an
archived Run stay readable, because an audit reads down from the Run; non-finite
evidence survives, since archiving is a fourth place the payload is serialised
and `evidence_json` exists so the backends cannot disagree; a cold Run moves and
one with a deletion date never does; recent and live work stay put; nothing is
archived twice; the batch limit bounds a sweep and a non-positive one is
refused; and the tier is off without an archive store.

One case is PostgreSQL-only and skips elsewhere:
`test_an_archived_row_without_a_tier_says_so_rather_than_vanishing`. Only a
store that really moves the payload can lose it, and the operator mistake worth
surviving is the archive URL going away after Runs were archived. It raises
`ArchivedPayloadUnavailable` — the record exists, the tier it moved to does not,
and reconfiguring makes the read work again.
