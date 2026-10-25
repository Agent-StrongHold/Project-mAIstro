---
inventory-delta:
  packages/maistro-core/tests: +52
---
# #924 M8-C5 trust/uncertainty memory-selection research harness (+52)

Evidence-only research harness for the M8-C5 leaf (epic #901): provenance-, trust-, and
uncertainty-aware memory selection and write suppression. No product code changed — the
module imports no maistro module (asserted by its own AST contract test; research
evidence, never an authority, per the M8 epic contract), so no vulture/reachability
identity changes.

`packages/maistro-core/tests/memory/test_m8c5_trust_aware_memory_research.py`
(+52 node IDs):

- `TestEvidenceOnlyContract` (6): no-maistro-import AST scan, advisory marker in the
  report ("experimental trust scores cannot override canonical security/authorization"),
  frozen result dataclasses, candidate features carry no ground-truth label fields (and
  the label table covers the whole corpus), closed reason vocabulary covering every
  write decision and entry disposition, corpus/query/axis integrity.
- `TestInstrumentArithmetic` (6): keyword-overlap replica hand cases, exact declared-axis
  cosines (1.0 / 0.0 / 1/√2 / 1/√3, zero vector), relevance = (overlap + cosine) ×
  weight on a hand case, the ADR-091 budget rule (always-include band never yields),
  duplicate-threshold boundary at the shipped 0.85 consolidation constant, recall-floor
  pool membership.
- `TestPoisonDetector` (7): each clause fires with its own reason code (injection
  marker, unattested owner attribution, contradiction of an attested fact), clean
  attested records pass, the "always"-containing legitimate fact survives strict
  markers while the loose marker set flags it (the measured false-positive axis),
  agreeing facts are not contradictions, detector determinism.
- `TestWritePolicies` (8): the shipped write path admits all 21 candidates including 4
  poison records (the baseline fact); selective write suppresses each class with exact
  reason codes including poison-before-duplicate precedence; zero false suppression of
  important records at the default floor; the 0.25/0.4 floor boundary on the
  0.3-confidence useful synthesis; exact write volume (21/1320 bytes vs 14/807, +7
  suppressed = 3 duplicates + 4 poison + 1 low-confidence); store contamination 4/21 vs
  0; the floor-sweep false-suppression curve; consolidation load 4 proposals vs 0.
- `TestContextEntryPolicies` (9): the SPEC-243 replica scores/orderings on a hand case
  (the m2 guess outranking the t2 measurement, each term hand-computed), poison leading
  q1/q3/q6 under the baseline, zero poisoned entries under trust-aware entry with
  `omit_poison_flagged` reasons, the useful model inference surviving (no blanket class
  ban), the q2 ordering flip, redundancy returning the attested original alone at
  q4/k=2, below-floor omission reasons, terminal dispositions for every candidate on
  every query with contiguous ranks, and the tight-budget interplay (the
  always-include band takes WISDOM-claiming poison regardless of budget; the protected
  path spends the same budget on the useful pair).
- `TestBenchmarkFindings` (9): exact headline cells (contamination 6/21 → 0, recall
  11/12 → 1.0, precision 11/21 → 12/19, attested share 7/21 → 11/19, store hygiene
  columns, false suppression 0 everywhere); the layering finding (one entry-side
  defense suffices on this corpus; the write layer's distinct value is store hygiene);
  small-k results (poison first for 4/7 queries, recall 3/12 vs 6/12, precision 3/7 vs
  6/7); the q7@k=2 window; attested share; the trust-blind-reader result; the flood
  sweep (contamination 6/21 → 7/21 saturating at k, recall 11/12 → 10/12, protected
  path clean at every level); report determinism (byte-equal JSON across builds); and
  measure-list schema completeness.
- `TestMutationProbes` (7): each headline mechanism disabled flips the finding naming
  it — poison detection off (contamination 0 → 4/19 via stopword overlap alone),
  entry-side exclusion off (0 → 2/19, with the duplicate clause as the pinned backstop
  for axis-mimicking records), trust prior and uncertainty discount each alone repairing
  q2 with both-off flipping it, the redundancy clause off (the duplicate label re-enters
  the window, precision 1/2), duplicate suppression off at write (16 stored, 2
  consolidation merges reappear), and loose markers causing exactly one false
  suppression of an important attested fact.

Additionally validated outside the suite: three file-level mutants (uncertainty discount
removed; duplicate clause removed at write; detector reduced to injection markers only)
fail 1, 8, and 11 tests respectively — exactly the pins naming the removed mechanisms.
