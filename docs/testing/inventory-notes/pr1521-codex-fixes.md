---
inventory-delta:
  packages/maistro-core/tests: +7
---
# pr1521-codex-fixes

Seven new tests in `packages/maistro-core/tests/scheduling/test_admission.py`,
one per Codex review finding on PR #1521 (duplicate-winner linkage, #1059),
each proving a real bug against the pre-fix code before the corresponding fix
went in:

- `TestRecoveredClaimsReserveTheirMaxRunsSlot` — a recovered pre-horizon claim
  now reserves its `max_runs` slot before `evaluate()` admits a new fire past
  it, instead of the two together spending one more run than the schedule
  allows.
- `TestRecoveredClaimsAreCountedOnce` — two tickers racing on the same stale
  snapshot and recovering the same pre-horizon claim now credit it exactly
  once; `ScheduleStore._advance` (`record_fire`'s shared cursor-advance) now
  takes the recovered occurrences themselves and only credits the ones still
  behind the freshly-read cursor, instead of trusting each caller's own
  (potentially duplicated) count.
- `TestPartialBatchCompletionIgnoresRecoveredPadding` — a seeded recovered
  claim padding `consumed` to the same length as `decision.fires` no longer
  masks a later fire in the *same* batch failing; completion is now tracked by
  whether the batch's own loop ran to the end, not by a length comparison.
- `TestRecoveryPastAGapTheOverlapPolicyLeft` — the pre-horizon claim walk no
  longer stops at the first occurrence without a Run: `CANCEL_OTHER` (and
  similar policies) can leave *legitimate* gaps before a crashed winner in
  the same never-recorded batch, so the walk now continues to the horizon
  (bounded by `_MAX_RECOVERY_PROBES`) instead of reading a legitimate gap as
  "nothing here" and missing the live Run past it.
- `TestClaimedSkipsAreNotDoubleReported` — an occurrence a claim lookup found
  a Run for is no longer also reported as an OVERLAP/EXHAUSTED skip;
  `evaluate()` decided the skip before it knew about the claim, and the two
  together said contradictory things about the same occurrence.
- `TestTruncatedOccurrencesAreStillProbedForClaims` — occurrences the
  512-enumeration cap truncates out of `evaluate()`'s own output are now
  still probed for existing claims (`SkipReason.TRUNCATED` left
  `_UNCLAIMABLE`), so a live winner sitting past the cap is no longer
  invisible to recovery.
- `TestConsumedOccurrencesKeepTheirOwnRunId` — `admit_due`'s consumed
  occurrences and their Run ids are now kept as paired `(moment, run_id)`
  tuples and sorted together, instead of as two parallel lists where only the
  timestamps were sorted — which could pair `last_run_id` with the wrong
  occurrence's Run whenever a seeded (off-batch) claim sat chronologically
  after one of the batch's own fires.

One existing test,
`TestRecoveryBeyondTheCatchUpHorizon::test_the_walk_stops_at_the_first_occurrence_without_a_run`,
tested the now-corrected "stop at first gap" behavior directly; it was
renamed to `test_the_walk_does_not_stop_at_the_first_occurrence_without_a_run`
and its probe-count assertion updated to match the walk's corrected,
horizon-bounded (not first-gap-bounded) reach. No other existing test's
behavior changed.
