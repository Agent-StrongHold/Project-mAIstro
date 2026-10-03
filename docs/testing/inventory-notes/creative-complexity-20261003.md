---
inventory-delta:
  packages/maistro-design/tests: +6
---

# Preserve creative Graph behavior while removing ungranted complexity

Six additive collected cases in `test_creative_graph.py` cover the public
invalidation and provenance seams extracted into smaller helpers:

- Two shared/local-change cases preserve added/removed request reasons,
  deterministic request ordering, and shared-change reason precedence.
- One unrelated-lineage case preserves the invalidation refusal.
- Three annotation-version cases (missing, zero and explicit override) preserve
  planned-only branches, orphan artifact records, malformed/non-artifact
  annotation filtering, canonical version fallbacks, empty-provenance defaults,
  and immutable historical records.

The existing execution, retry, reconnect, historical lineage and generation
refusal cases remain unchanged. No baseline, grant or gate threshold is raised.
This note records only these six new cases; unrelated root-suite drift is
owned by the separate merge-queue inventory repair.
