---
inventory-delta:
  packages/maistro-core/tests: +6
---
# pr1533-codex-fixes

Six new tests in `packages/maistro-core/tests/scheduling/test_admission.py`,
one set per Codex review finding on PR #1533 (a fresh review pass on top of
#1059's duplicate-winner linkage work), each proving a real bug against the
pre-fix code before the corresponding fix went in:

- `TestRecoveryCreditSurvivesAMissedClaim` (1 test) — a rival ticker whose
  pre-horizon claim lookup transiently fails no longer costs the recovery
  credit for good. That ticker still has its own, unrelated due fires to
  admit, and `record_fire`'s cursor advance follows *those*, not the claim it
  missed — so it carries `last_fired_at` straight past the crashed winner
  with no idea it exists. A second ticker that *did* see the claim used to
  find the cursor already past it and stand down, because crediting was
  decided by comparing the claim against cursor position: "the cursor moved
  past it" read as "someone must have credited it," which was false exactly
  here. `Schedule` now carries `recovered_occurrences`, a durable,
  bounded (`store._MAX_RECOVERED_OCCURRENCES`), per-occurrence credit ledger
  that `_advance` checks instead, so the second ticker's credit lands
  regardless of where the cursor sits.

- `TestTruncatedClaimsAreProbedInOneBatch` (2 tests) — the truncated-tail
  claim lookup #1059 added (so a live winner past the 512-occurrence
  enumeration cap is not invisible to recovery) no longer issues one awaited
  Run-store query per truncated occurrence. `RunStore` gains
  `get_runs_for_occurrences`, a batched twin of `get_run_for_occurrence`
  (implemented for `InMemoryRunStore`, `SqliteRunStore` via `json_each`, and
  `PgRunStore` via `= ANY($n::text[])`), and the truncated tail is probed
  through one call, bounded by the new `_MAX_TRUNCATED_CLAIM_PROBES` (the
  newest of the dropped tail first) — closing the gap where a schedule stuck
  far enough behind to truncate tens of thousands of occurrences turned one
  recovery tick into tens of thousands of serial queries. One test proves the
  batching (one call, not N) and that the original missing-winner fix still
  holds; the other proves the bound — a winner within the newest
  `_MAX_TRUNCATED_CLAIM_PROBES` of the tail is still found, one further back
  is not, and that boundary is asserted directly rather than left implicit.

- `TestRecordFireStaysCompatibleWithAnOlderScheduleStore` (3 tests) —
  `ScheduleRunAdmitter` named `record_fire`'s `recovered=` keyword on every
  call, recovering or not, so an external `ScheduleStore` implementation
  using the previously valid signature (no `recovered` parameter at all)
  raised `TypeError` on every ordinary recurring fire after upgrading, not
  merely a recovering one — the keyword's own default value on the *callee*
  side protects nothing once the *caller* always names it. `_record_fire`
  now omits the keyword entirely when there is nothing to credit, which
  keeps the common, no-recovery case working unchanged against an older
  store; a genuinely recovered claim still names it, and still fails loudly
  against a store that cannot accept it, which is the correct outcome —
  silently dropping the keyword there would silently drop the credit,
  reintroducing the exact under-counting bug `recovered` exists to close.
  One test covers the ordinary case, one covers the due-cursor-only call
  site that never named `recovered` even before this fix (asserted so a
  future change to it cannot regress that silently), and one asserts the
  loud failure is preserved for a genuinely recovered claim.

No existing test's behavior changed.
