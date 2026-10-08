---
inventory-delta:
  packages/maistro-rsi/tests: +41
---
# #922 M8-C3 adaptive context budgeting research harness (+41)

Evidence-only benchmark harness for the M8-C3 research leaf (epic #901): evaluate adaptive
context budgeting, hierarchical compression, and selective omission against the shipped
fixed context budget. No product code changed — the module imports no maistro module
(research evidence, never an authority, per the epic contract; AST-pinned by its own
contract test), and the canonical assembly seam (`maistro.memory.context_assembly`,
ADR-091 / SPEC-244) is untouched.

`test_m8c3_context_budgeting_research.py` (+41 node IDs in `packages/maistro-rsi/tests`):

- `TestEvidenceOnlyContract` (2): advisory marker + no-maistro-import AST scan.
- `TestReplicaIdentities` (5): the production math hand-checked before any measurement —
  `len // 4` token estimate, band overspend at a zero budget, skip-not-break without
  slicing, zero-score rank drops with stable sort, weight-tier ordering.
- `TestCorpusSanity` (7): fact probes verbatim in anchors, pinned corpus shape (30 memories
  / 12 queries / 12 facts / 4 duplicate pairs / 5 band-cuttable facts), weights on the
  production tier ladder, duplicate pairs above tau while same-topic non-pairs stay below,
  qualifiers outside sentence one (the distortion measure's precondition), adversarial
  WISDOM zero lexical overlap with every query, benchmark determinism.
- `TestPolicyMechanics` (6): complexity buckets monotone with pinned budget arithmetic,
  density saturation math, omission dropping only flagged duplicates across all queries,
  margin plateau exactly the rank-prefix before the cliff, summary tier engaging only under
  pressure, no memory ever truncated (the #622 rule) under any policy.
- `TestBenchmarkFindings` (9): the pinned corpus facts — fixed frontier monotone in budget;
  band overspend on every query at tight budgets; band-confined losses (banded facts never
  budget-lost at any swept budget); complexity scaling recovers the crowd-out losses at
  lower mean spend than the 120 point; density holds that recall at its mean spend;
  omission saves tokens with identical recall (the band absorbs the freed budget — honest
  negative); the margin stop is a measured negative; full_adaptive pays a composition tax
  (the summary allowance re-loses the fact complexity scaling rescued); work-unit
  orderings.
- `TestSummariesDistortion` (4): the naive summarizer distorts qualifier probes the safe
  one serves whole; marker-sentence retention; zero fabrication for both summarizers over
  every topic; served probes always verbatim and distortion a subset of served.
- `TestStabilityAcrossWindowSizes` (4): fixed degrades at the smallest window while
  hierarchy is recall-neutral on this corpus (the C2 boundary re-found one layer up, pinned
  as equality); summaries engage only under pressure; pressure costs at most its allowance
  over fixed; spend bounded by window share + seed + allowance.
- `TestNoiseSweep` (3): high-weight filler injection never improves recall, strictly
  degrades the fixed policy, and the density stop absorbs it best.

Every pinned finding was mutation-checked (recorded in
`docs/research/922-adaptive-context-budgeting.md`): removing the always-include band,
freezing the complexity multiplier, disabling omission, removing the summary allowance,
stripping the summarizer's marker sentences, injecting a fabricated summary sentence,
turning skip-not-break into break, disabling the density stop, and padding zero-score rows
into the rank each flip exactly the pins naming those mechanisms. All metrics are
deterministic (byte-equal across runs); latency is work-unit accounting, never wall-clock.
