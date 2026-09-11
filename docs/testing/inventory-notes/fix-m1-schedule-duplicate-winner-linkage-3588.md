---
inventory-delta:
  packages/maistro-core/tests: +41
---
# fix-m1-schedule-duplicate-winner-linkage-3588

Forty-one new tests for recovering the Run that won an occurrence claim
(#1059); nothing was removed or moved. Twenty-four came with the change, and
seventeen with the Codex review findings on it (below).

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

The review findings added seventeen more. Six behavioral cases in
`test_admission.py` (`TestRecoverySeesTheRunStoreBeforeThePolicy`): a
CANCEL_OTHER tick finds the crashed winner the pointer never named, admits the
newer occurrence, asks for the winner's cancellation and reports it as
`active_run_id`; a SKIP tick defers to that winner instead of running beside
it; a crash-recovered winner is counted once and can exhaust `max_runs=1`; two
tickers consuming one occurrence count it once; an unresolvable newest winner
under ALLOW yields the pointer to this ticker's newest Run rather than one from
before the batch; and a delayed ticker's write cannot move the cursor backward.
Three store conformance cases in `test_store.py`, counted per backend (nine
collected): a stale write moves neither cursor, pointer nor due time backward;
an occurrence is counted once however many writers record it; and reaching
`max_runs` disables the schedule without being asked. One archive conformance
case in `packages/maistro-core/tests/runs/test_archive_conformance.py`
(memory and PostgreSQL, two collected) proves an archived scheduled Run still
holds its occurrence claim — a second Run is refused and
`get_run_for_occurrence` still resolves it — which is what migration 034's
promoted claim columns exist for.
