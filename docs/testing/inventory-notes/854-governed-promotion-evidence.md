---
inventory-delta:
  packages/maistro-evolve/tests: +16
---

# Governed champion selection and promotion evidence (#854)

Adds the behavioral proof suite for #21's one canonical
candidate → independent evaluation → governed promotion contract
(`packages/maistro-evolve/src/maistro_evolve/promotion.py`), exercised through
the real `PopulationStore`/`EvolutionCycle` surfaces:

- a lucky single sample is refused by champion selection and promotion
  (insufficient independent evidence, `min_samples_per_benchmark`);
- best-of-N winners stay promotion-ineligible until a fresh post-acceptance
  sample (winner's-curse guard) and unstable sample spread fails the
  uncertainty bound;
- unevaluated offspring are excluded from selection/promotion and are not
  culled for lacking a score;
- gate-failed, stale (`max_evidence_age_cycles`), objective-mismatched, and
  unapproved candidates are excluded at the right gate (approval binds
  promotion, not selection);
- a worse candidate cannot replace a stronger incumbent by calling
  `promote()` later (`min_promotion_margin` under one immutable objective
  version); a genuinely better, independently confirmed candidate promotes
  with a complete decision record;
- the production cycle re-samples already-evaluated genomes
  (`reconfirm_per_cycle`), so the declared EMA estimator actually runs through
  the real cycle instead of a first sample being permanent.

Existing champion/promotion tests were moved onto the governed contract
(evidence stamps + margin), including the formal audit-trail conformance
models, which now drive successive strictly-better promotions so the #342
audit properties keep exercising real transitions; rejections are audited as
`promotion_attempt` + `promotion_rejected` with reasons.
