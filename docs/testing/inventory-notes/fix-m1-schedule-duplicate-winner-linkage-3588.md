---
inventory-delta:
  packages/maistro-core/tests: +24
---
# fix-m1-schedule-duplicate-winner-linkage-3588

Twenty-four new tests for recovering the Run that won an occurrence claim
(#1059); nothing was removed or moved.

Six behavioral cases in `packages/maistro-core/tests/scheduling/test_admission.py`
(`TestADuplicateClaimLinksTheWinningRun`) drive `ScheduleRunAdmitter` on the
in-memory stores through the issue's crash sequence: a ticker creates the Run
for an occurrence and dies before `record_fire`, a second ticker is refused by
the claim and must leave `last_run_id` naming the winner; a SKIP schedule then
sees that live Run and drops its next occurrence; a finished winner is linked
but does not block; two tickers racing one occurrence converge on one Run id
and one cursor; under ALLOW the pointer follows the newest consumed occurrence
whichever ticker admitted it; and a winner the store can no longer resolve
leaves the existing pointer untouched.

Four conformance cases in `packages/maistro-core/tests/runs/test_spine_conformance.py`
cover the new `RunStore.get_run_for_occurrence()` on all three backends (twelve
collected items): the claiming Run resolves from its `(schedule_id,
scheduled_for)`, an unclaimed occurrence resolves to nothing, every loser of
the eight-ticker race resolves the same winner, and a deleted winner no longer
resolves.

Two restart cases in the new `packages/maistro-core/tests/runs/test_schedule_winner_linkage.py`
(six collected items) repeat the crash on the claim-capable `schedule_spine`,
reopening the durable store as a restarted worker would before the second
ticker runs, and prove the linked Run is the one the next occurrence's overlap
decision is judged against. The PostgreSQL legs of both durable suites run
where `MAISTRO_TEST_PG_DSN` is set and skip otherwise.
