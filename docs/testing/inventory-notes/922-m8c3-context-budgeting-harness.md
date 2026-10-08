---
inventory-delta:
  packages/maistro-rsi/tests: +41
---
# #922 M8-C3 adaptive context budgeting research harness (+41)

Evidence-only benchmark harness for the M8-C3 research leaf (epic #901): evaluate adaptive
context budgeting, hierarchical compression, and selective omission against the shipped
fixed context budget — including the shipped whole-block delivery gate
(`context_builder._apply_memory`), the layer-1 pool floor (`min_weight =
BUDGET_INCLUDE_WEIGHT`), and the band-derived layer-3 wisdom force-feed. No product code
changed — the module imports no maistro module (research evidence, never an authority, per
the epic contract; AST-pinned by its own contract test), and the canonical assembly seam
(`maistro.memory.context_assembly`, ADR-091 / SPEC-244) is untouched.

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
  density saturation math, omission dropping every trailing flagged duplicate (positive
  direction, not merely nothing-but-duplicates), margin plateau exactly the rank-prefix
  before the cliff, pressure delivering nothing when the whole-block gate trips, no memory
  ever truncated (the #622 rule) under any policy.
- `TestBenchmarkFindings` (10): the pinned corpus facts — fixed frontier monotone in budget
  (all zeros until gate fit); the always-include band tripping the whole-block gate at the
  swept budgets; band survival conditional on gate delivery; complexity scaling unable to
  recover a tripped gate; sub-gate complexity adaptivity buying nothing; the density cap
  recovering the fixed sweep's gate losses at a pinned 27.83 mean tokens; omission
  indistinguishable below the gate (identical zeros); the margin stop netting the sweep's
  best recall at its pinned frontier (0.400 / 64.1); the full stack's reserve tripping the
  gate everywhere (total loss, not a tax); work-unit orderings.
- `TestSummariesDistortion` (4): the naive summarizer distorts qualifier probes the safe
  one serves whole; marker-sentence retention; zero fabrication for both summarizers over
  every topic; served probes always verbatim and distortion a subset of served.
- `TestStabilityAcrossWindowSizes` (4): fixed degrades at the smallest window while the
  hierarchical tier ties fixed at every window (the band-derived seed rides in both
  policies' blocks, so the reservation buys no gate fit); pressure summaries never survive
  delivery; pressure spend at most its allowance over fixed; spend bounded by window share
  + seed + allowance.
- `TestNoiseSweep` (3): high-weight filler injection never improves recall, is masked by
  gate fit (identical delivery at fixed 120), and the density stop absorbs it at least as
  well as fixed.

Mutation record (head bbb23f583, exact flipped pins measured): deleting the always-include
band from `_pack` flips the band-overspend identity pin; freezing the complexity multiplier
flips the complexity monotonicity pin; disabling omission flips the drops-only pin's
positive direction; stripping the summarizer's marker sentences flips the retention pin;
injecting a fabricated summary sentence flips exactly the fabrication pin; turning
skip-not-break into break flips three pins; disabling the density stop flips its pinned
spend; padding zero-score rows into the rank flips seven pins; reverting the seed to an ID
list flips four pins (the seed's production fidelity is itself mutation-guarded); removing
the margin cliff flips the margin frontier pin. Recorded blind spot: removing the summary
allowance flips nothing — under the gate the tier never delivers, so its allowance is
measurement-invisible; the never-survives pin holds trivially without it. All metrics are
deterministic (byte-equal across runs); latency is work-unit accounting, never wall-clock.
