---
inventory-delta:
  packages/maistro-core/tests: +3
---
# Recovery claim-steal guard inventory

CI-repair evidence for the `coverage (PostgreSQL)` gate failure at
540344011373: the job failed once on
`test_two_recovery_stores_cannot_poll_the_same_observation_twice[sqlite]`,
whose final durable record was a fresh 60s recovery claim
(`resume_at` = fake tick moment + `GRAPH_RECOVERY_CLAIM_TTL`) that had
bumped the continuation version under the live worker, so the worker's
terminal write was refused as a version regression and the Run was left
stranded RUNNING.

`packages/maistro-core/src/maistro/graph/durable_runs/attempt_executor.py`
now refuses (`LiveAttemptOwned`) to claim a RUNNING record whose
`resume_at` is still ahead of the resuming tick's own moment — the same
liveness predicate `CanonicalDurableRunStore.reconcile_persistence` already
uses — and `resume_durable_graph` takes that moment as `now`, threaded from
`resume_due_graph_runs`. Expired claims stay stealable; WAITING parks,
HITL pauses and queued recovery are untouched.

Delta provenance, all in `packages/maistro-core/tests`:

- `test_recovery_disposition.py` +2: `test_resume_refuses_a_live_recovery_claim_on_a_running_run`
  (a live claim cannot be stolen; the stranded worker executes nothing) and
  `test_resume_still_steals_an_expired_recovery_claim` (an expired claim is
  still the proof of death recovery requires). The refusal test fails with
  `DID NOT RAISE` against the unguarded resume.
- `test_agents/.../test_coin_ledger_conformance.py` +1 from the salvage
  commit `c414a5c21` ("conformance retry probe verifies the complete
  original receipt"), which landed on this branch after the recorded
  inventory was frozen and added
  `TestAdapterConformance::test_a_ledger_that_recomputes_a_retry_receipt_fails_named`
  without recording its own delta.
