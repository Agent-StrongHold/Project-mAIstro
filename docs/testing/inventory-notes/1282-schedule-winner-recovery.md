---
inventory-delta:
  packages/maistro-core/tests: +9
---

Adds the recovery half of the duplicate-winner linkage residue (#1059 review, ported from the superseded #1282 branch onto develop's reactive design from #1269).

`TestRecoverySeesTheRunStoreBeforeThePolicy` (3 tests) pins that the admitter reads the Run store's occurrence claims *before* the overlap policy: a crashed winner the pointer never named is what CANCEL_OTHER asks to cancel and what SKIP defers to, and two tickers consuming one occurrence count it once. Counting on enumerated occurrences follows develop's delta contract — the winner's ticker counts, a claimant that finds the Run never does; the branch's exact per-occurrence store dedup was superseded and is not asserted.

`TestRecoveryBeyondTheCatchUpHorizon` (6 tests) pins the pre-horizon recovery walk: winners that crashed behind the catch-up horizon are never enumerated, so the admitter walks occurrence claims forward from the cursor up to the enumeration start — recovering linkage for SKIP/BUFFER_ONE/CANCEL_OTHER alike, counting the provably-unrecorded walk claims exactly once (they can exhaust `max_runs`), bounding the walk at the first occurrence without a Run, and costing an idle tick zero lookups beyond the enumeration probes it already made.

A shared `_crashed_before_record_fire` helper reproduces the torn state: the Run exists, the cursor was never stamped.
