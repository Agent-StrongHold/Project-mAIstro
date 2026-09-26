---
inventory-delta:
  packages/maistro-core/tests: +1
---
# m1-1176-b1-ambiguous-race

Adds `test_ambiguous_resolution_rechecks_a_claim_that_lost_a_race` to cover the
retry race between Run discovery and recording the outcome. It prevents a
stale begun receipt with no `run_id` from being returned while a takeover
claim is still admitting, and verifies the retry re-reads the durable claim and
returns the winner's receipt and Run.
