---
inventory-delta:
  tests/: +24
---
# Ordered body-status declarations and metric-v2 ledger description

Follow-up to PR #1532 adds 24 root-suite cases without removing existing tests:

- Sixteen ordered-list cases: dot and closing-parenthesis markers across both
  ADR/spec roots and all four supported initial indentation widths (0–3).
- Two additional controls preserve the four-space code-block exemption for
  ordered markers.
- Five grammar controls cover the nine-digit Markdown boundary and reject
  ten-digit, alphabetic, signed, and non-whitespace-delimited pseudo-markers.
- One sandboxed `--update` case checks that the generated ledger describes
  absence regardless of agreement while preserving metric version 2 and empty
  known/details collections. It does not update the repository's baseline.

Against PR head `8681590ec3de4b4a3762175d1e9de49c6a6d0df2`, root collection
moves from 4851 to 4875, exactly +24. The sanctioned inventory script generated
this delta; no unrelated drift, baseline authorization or tolerance was added.
Before the checker repair, 18 cases failed and 62 passed; after the repair,
the checker and provenance suites passed all 96 cases.
