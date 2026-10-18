---
inventory-delta:
  tests/: +44
---

# 929 Graph-pattern induction/reuse research bench

Implements the #929 (RESEARCH M8-D5) deliverable: an offline, deterministic
bench mining successful Runs into reusable Graph motifs and comparing reuse
against from-scratch planning, plus the research record and INCUBATE
disposition in `docs/research/929-graph-pattern-induction-reuse.md` with
numbers in `docs/benchmarks/graph-pattern-reuse-baseline.json`. No product
code changes.

All additions, no removals:

- `scripts/bench_graph_pattern_reuse.py` — the bench itself (measured root:
  `scripts/` is covered by the quality.yml producer). Mining reads the real
  canonical spine (`Run` over `GraphSnapshot` with `NodeRun`/`Attempt`/
  `AttemptResult`/`AcceptedNodeOutcome` records); induction registers real
  `GraphTemplate` objects in the real `InMemoryGraphTemplateStore`, held at
  ``lifecycle="candidate"`` per ADR-082926-65bf so no execution path resolves
  them; every reused Graph comes from the real `GraphTemplate.instantiate`.
- `tests/test_bench_graph_pattern_reuse.py` — **+44 tests** in the root
  `tests/` suite: structural signatures are the kind-level isomorphism class
  (node-rename-invariant, direction-sensitive); latent-world drift hits only
  the drift family's unvalidated structures while stated specs stay untouched;
  recorded successful Runs complete every node through an accepted outcome and
  failed Runs fail exactly one without accepting; mining counts only
  COMPLETED Runs and refuses a high-support single-instance structure as an
  overfit trap; induced templates are candidates the execution door refuses
  (`require_template` both unversioned and version-pinned, unversioned
  `store.get` returns None) whose `instantiate` carries exact-version
  `TemplateProvenance` onto a fresh Graph; templates document their evidence
  without execution identity and the real `RUNTIME_STATE_FIELDS` validator
  refuses a template carrying `run_id`; planner cost contracts, guard
  quarantine firing exactly once past the window floor, forced-transfer
  skipping own-family motifs; full-experiment determinism, payload shape,
  drift-boundary checkpoints, re-mined library growth, stale-failure
  attribution (naive bleeds, guard bounds, scratch zero — across five seeds);
  aggregation mean/std, verdict thresholds, and `main()`'s published JSON.

The bench is deterministic (seeded RNGs, fixed record timestamps, no
wall-clock assertions) and runs offline at small scale to respect the root
suite's `--timeout=30` producer budget (full new suite: ~5 s).
