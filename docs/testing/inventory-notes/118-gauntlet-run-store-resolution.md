---
inventory-delta:
  packages/maistro-core/tests: +5
---
# 118-gauntlet-run-store-resolution

Four of the five new node IDs are this repair's new tests in
`packages/maistro-core/tests/memory/learnings/test_gauntlet.py`, covering the
Gauntlet's run-store resolution seam (#118):

- `test_a_run_id_that_resolves_to_nothing_is_rejected` — a trial `run_id` the
  canonical Run store cannot resolve (fabricated, mistyped, or deleted) fails
  `canonical_runs`; an audit trail that cannot be resolved is no trail.
- `test_a_run_that_never_completed_cannot_validate` — a named Run that is
  still RUNNING, FAILED, or CANCELLED fails `run_outcome`; the record's own
  `success` flag is not the spine's word.
- `test_run_provenance_must_bind_to_this_candidate_and_context` — a real,
  completed Run whose provenance does not bind it to this candidate's frozen
  content hash, the trial's context id, the gauntlet-trial purpose, and the
  reported held-out flag fails `run_provenance`.
- `test_without_a_run_store_the_gate_fails_closed` — with no `run_store`
  configured, any named run id fails the gate; unresolvable provenance cannot
  justify collective promotion.

The remaining +1 is residual drift introduced by the develop integration this
branch merged (M4-A6 lineage/archive with #780/#791/#774/#792 renumbering):
the summed `inventory-delta` blocks that integration carried under-record its
merged `packages/maistro-core/tests` content by one node. The exact test is
not attributable from the notes alone; the merge-queue driver measured the
same +5 with this repair's four tests already in place, so the residual +1
pre-existed this repair and is recorded here so the ledger matches reachable
truth. No test was removed.
