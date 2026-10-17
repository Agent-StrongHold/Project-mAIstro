---
inventory-delta:
  packages/maistro-core/tests: +1
---

# auto-119: pin the dedup epistemic-type move in `InMemoryLearningStore`

Prior verification of this lane recorded that `InMemoryLearningStore.store`'s
dedup path moves `epistemic_type` with the reworded text
(`packages/maistro-core/src/maistro/memory/learnings/store.py`, the
"the epistemic type moves with the text it qualifies" block) with no direct
pinning test — the one unpinned surface of the M4-B3 acceptance criterion
"epistemic type is explicit and usable by retrieval/ranking".

`test_store_dedup_reword_moves_the_epistemic_type_and_its_rank_bonus`
pins it through the public API, structure over wall-clock:

- a `TESTED` learning (rank bonus 0.4) and a `REPORTED` rival (0.2) share the
  `deploy` trigger key; on the keyword tie the TESTED bonus orders retrieval;
- storing a `COUNTERFACTUAL` reword (bonus 0.0, same axes, overlapping keys)
  replaces the row in place — same id returned, new text and new type on the
  surviving row;
- retrieval ordering flips: the reworded claim loses the TESTED bonus and the
  REPORTED rival now outranks it on the same tie, so the type move is proven
  behaviourally, not just as a field write.

Regression proof: with the type-move line disabled, the test fails at the
surviving-type assertion (the old TESTED type sticks and the ordering stays
put); re-enabled, it passes. No production code changed in this delta — the
line was already correct; only the pin was missing.
