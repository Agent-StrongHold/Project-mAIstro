---
inventory-delta:
  packages/maistro-core/tests: +84
---

# 105 working memory: durable log-as-context

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Implementation round for #105 (EPIC M4-H) via direct child #301: the
append-only per-Workspace observation log, its SQLite durable twin, the
ephemeral Ladybug-role projection rebuilt from it (ADR-082226-5104 §5-6),
structural recall, GUIDE/WORKING rendering, simplification/hard resets, and
the redundancy and fresh-vs-lineage measurements.

What moved (84 node IDs in two files under `packages/maistro-core/tests/memory/`):

- `test_working_log_store_conformance.py` (+23): the store contract runs
  **both legs** — the in-memory reference and the SQLite twin — over the same
  calls (append/seq assignment, filters, addressable results, marker entries,
  purge), plus a restart test that reopens the SQLite database, re-reads the
  reset marker's survival set and a result payload, and re-runs
  `ensure_schema()` idempotently. This is the same dual-leg shape the scope
  store conformance suite uses, so a twin that disagrees with the reference
  fails here rather than in production.
- `test_working_memory.py` (+61): working-set derivation (reset survival sets,
  summary folds, `survive_reset` flag crossing reset positions), rebuild
  equivalence (a projection rebuilt by hydration answers exactly like one
  updated incrementally — the property that makes the projection disposable),
  manager lifecycle (per-Workspace isolation, idle eviction), lexical + lineage
  recall with duplicate collapse, GUIDE/WORKING rendering (full payloads stay
  behind references), the two measurements (redundant hypotheses without any
  embedding model; fresh-vs-lineage scoring), and container wiring (SQLite pool
  -> durable twin, no pool -> loud in-memory fallback).

Coverage intent: the losslessness invariant (nothing ever edits or deletes an
entry except the driven `purge_workspace`) is asserted both directly (append +
reset + purge counts) and structurally (rebuild equivalence), because that
invariant is what lets every other behaviour be a derivation over the log.
