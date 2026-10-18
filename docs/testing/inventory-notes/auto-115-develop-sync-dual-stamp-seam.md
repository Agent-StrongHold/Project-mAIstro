---
inventory-delta:
  packages/maistro-evolve/tests: +3
---

# Develop-sync dual-stamp seam — M4-A6 provenance x M4-A8 origin (#115)

The develop sync merged the M4-A6 candidate-archive lineage system
(`archive.CandidateProvenance` / `stamp_provenance`, issue #113) into the
branch that carries the M4-A8 producer-attribution system
(`attribution.CandidateOrigin` / `stamp_origin`). Producers now stamp BOTH
records on every child; neither side's existing suite alone pins that both
records survive on the same candidate, so the reconciliation added
`TestDualStampSeam` in `packages/maistro-evolve/tests/test_attribution.py`:

- a `crossover_and_mutate` child passes the promotion gate's
  `complete_provenance` (operator `crossover`, parents = the two STORED
  parents, legacy `parent_a_id`/`parent_b_id` re-derived) while its
  `CandidateOrigin` still names the composite mutation producer and the
  crossover upstream chain;
- a `mutate_selected` child (a producer only M4-A8 knew about) is also
  promotion-gate complete — provenance stamped with the applied subset as
  `detail` — alongside its `mutate_selected` origin;
- a plain `crossover` child carries both records with consistent parent ids.

Quality/vulture ledger note: the same sync let `archive.stamp_provenance`
read/write `parent_b_id` and develop's #1829 work read `decided_by`, so four
vulture identities became used and were pruned from
`quality/vulture-baseline.json` (no rows added; net debt 1359 → 1350).
