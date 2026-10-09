---
inventory-delta:
  packages/maistro-rsi/tests: +34
---
# #894 M8-A14 critical-zone mutation strategy research harness (+34)

Evidence-only research harness for the M8-A14 leaf (epic #880): define and test a
critical-zone mutation strategy for architectural invariants. No product code changed —
the module imports no `maistro` module (research evidence, never an authority, per the
epic contract), and the canonical authorization seam
(`maistro.security.trust_boundary`) is untouched.

`test_m8a14_critical_zone_mutation_research.py` (+34 node IDs):

- `TestEvidenceOnlyContract` (3): the `ADVISORY_ONLY` marker, frozen survivor
  records, and the narrowness of the hand-verified claim (only lines 32 and 106).
- `TestRecordedRunIntegrity` (4): totals of the recorded cosmic-ray 8.7.0
  prototype run partition correctly (103 mutants = 53 killed + 50 survivors; the
  four definitions sum to the total), the operator-family table covers exactly
  cosmic-ray 8.7's 16 families / 213 variants, and the measured unit costs are
  plausible (~2.3 s/mutant).
- `TestZoneSelectionCriteria` (4): the prototype zone passes all five criteria;
  each criterion individually rejects; a large authority module fails on the
  budget (C3) rather than the authority role (C1); estimates scale from the
  measured mutant density.
- `TestOperatorSemanticRiskTaxonomy` (5): decision-flip families at runtime,
  binary-operator magnitude risk, annotation/message contexts are
  equivalent-by-construction regardless of family, and the TTL arithmetic is the
  concrete high-consequence magnitude case.
- `TestSurvivorTaxonomyOnRecordedRun` (6): all 50 recorded survivors classify
  into the five classes with exact counts (25/2/2/19/2), the accounting
  arithmetic (raw 51.5% vs meaningful 67.9% kill rate), both hand-verified
  flagships sit in the actionable class, the 22 annotation survivors are the
  largest equivalent block, and every survivor carries a semantic role.
- `TestMiniatureMutationEngine` (8): the survivor mechanism made deterministic —
  the original guard model passes every oracle, each of the five representative
  mutators (deny-all flip, fail-safe default flip, action-guard `>=` bypass,
  scope-conjunction OR, deleted `not`) is distinguishable under the full battery
  and killed by its recorded violation set (four by their named oracle alone;
  the deny-all flip by two — `action_guards_are_exact` also kills it), and each
  recorded flagship mechanism is demonstrated to survive without its oracle.
- `TestPolicyAndCiFeasibility` (4): one zone fits a PR slot (~4 min), a
  seven-zone curated set fits nightly but not PR CI, the near-zero-survivor
  policy requires generation-time exclusion of equivalents, and the stricter
  local policy dominates broad score chasing on this run's numbers (31 of 50
  survivors non-actionable vs 19 actionable).

The recorded run data (cosmic-ray 8.7.0 over
`packages/maistro-core/src/maistro/security/trust_boundary.py` vs its mirror
suite, 2026-10-08) is experimental output embedded as evidence — the
reproduction procedure and the full survivor table live in
`docs/research/894-critical-zone-mutation-strategy.md`.

Net collected node-ID delta: **+34** (new file, no parametrization).

## 2026-10-08 repair (develop-sync rounds)

Two develop-sync rounds are recorded here.

First round: resolved a preserved origin/develop sync conflict in
`docs/research/README.md` (union of the #894 and #896 index rows; INCUBATE count
corrected to four) and corrected the miniature-engine kill-mapping claims to the
measured violation sets: executing the battery showed the deny-all fallback flip is
killed by two oracles (`deny_all_fallback` and `action_guards_are_exact`), not one, so
`test_each_oracle_kills_exactly_its_named_mutator` (membership-only) became
`test_battery_kills_match_the_recorded_violation_sets`, asserting the exact
per-mutator sets (`EXACT_VIOLATIONS`). Companion prose corrections in
`docs/research/894-critical-zone-mutation-strategy.md` (C5 scope, PEP 563
equivalence phrasing, TTL operator directions, broad-gate comparison vs the
existing annotation filter).

Second round (this worktree): origin/develop advanced by 8 commits and the
preserved merge had one remaining conflict in `docs/research/README.md` — both
sides of the closing INCUBATE paragraph claimed "four" with disjoint leaf lists.
Resolved to the union of the merged index table: **five** INCUBATE leaves
(#894, #896, #914, #916, and #929, which develop added as INCUBATE via the
graph-pattern-reuse note). Harness and note content unchanged in this round;
node count still 34, so the +34 delta above remains exact.
