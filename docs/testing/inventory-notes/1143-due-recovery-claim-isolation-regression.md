---
inventory-delta:
  packages/maistro-core/tests: +1
---

# Due-recovery claimed-candidate regression (#1143)

Adds one regression to
`packages/maistro-core/tests/graph/durable_runs/test_recovery_wakeup.py`:
`test_a_partially_claimed_poisoned_candidate_stays_recoverable_after_its_claim_expires`.
It closes the coverage gap between the two recovery seams' #1143 fixtures —
the queued path already proved a partially claimed candidate is never
swallowed, but the due path had no equivalent. The fixture plants a poisoned
due candidate whose resume persists the recovery claim (`resume_at` pushed to
the claim TTL) before failing, then proves across three ticks that the
failure is isolated with sanitized evidence, the live claim is never
re-attempted (no double-resume), and the candidate is retried once the claim
expires.
