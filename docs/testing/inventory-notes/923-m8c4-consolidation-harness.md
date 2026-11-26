---
inventory-delta:
  packages/maistro-core/tests: +50
---
# 923 M8-C4: consolidation / temporal-contradiction / forgetting research harness (+50)

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Issue #923 (epic #901, initiative #879) asked for an evaluation of episodic-to-semantic
consolidation, temporal contradiction handling, and forgetting, with a
GRADUATE/INCUBATE/REJECT/WATCH disposition and the constraint that consolidation may not
erase provenance or mutate canonical history invisibly. No real Workspace-history experiment
exists in deterministic CI, so the research record
(`docs/research/923-episodic-consolidation-temporal-forgetting.md`) registers WATCH and this
change adds the reproducible measurement machinery the issue's measure list demands, as one
self-contained test module in `packages/maistro-core/tests/memory/`
(`test_m8c4_consolidation_temporal_forgetting_research.py`, +50 node IDs).

The module is deliberately test-side and imports no maistro module (asserted by its own AST
contract test): it is research evidence, not product code, so no vulture/reachability
identity changes. The 50 cases cover: the evidence-only contract itself (advisory marker,
no-maistro-import AST scan, empty/duplicate/ghost-reference history rejections, question-kind
and contradiction-pair validation, tier-band weight rejection, evidence-link requirement for
contradiction registration, wrongness-needs-parent strategy validation, tiny-corpus
refusal); hand-checked arithmetic on a pinned 8-episode/6-question fixture (production
formula scores exact, stable-tiebreak stale lead on raw, temporal promotion with audit-mode
reachability, merge weight 5/14 with retained tombstone chain, contradiction flag lowering
both sides once with declared-supersession exemption, decay to the OBSERVATION floor vs the
floorless variant's information loss, purge breaking chain integrity 0.75 and ledger replay,
daily all-pairs cost 43 with the absorbed-skip explained, quadratic cost scaling); and a
seeded 48-episode/30-question corpus asserting only construction guarantees (current-fact
accuracy 1/3 raw -> 2/3 temporal -> 1.0 combined, stale intrusion repaired per versioned
query, decay sinking obsolete rows to floor without information loss, audit recall 1.0 for
every retaining arm vs <1.0 under either erasure variant, contradiction quality 0.0 -> 1.0,
live rows 48 -> 42 with merges == duplicate groups, frozen JSON report round-trip, and the
frozen hand-fixture headline table including the replay/retention invariant).
