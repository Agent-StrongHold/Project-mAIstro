---
inventory-delta:
  tests/: +5
---
# 1682-complexity-gate-scope

Issue #1682 widened the complexity gates (radon ratchet, xenon, interrogate)
from `packages/maistro-core/src` to every shipped package's `src/`, with the
grants and the per-identity ledger landing through #1683/#1684/#1793. The
validation round behind this note re-proved the widened state at head
`31d891a561df` (radon ratchet exit 0 at 143/143; xenon 143 block identities
matching the ledger one-for-one, 0 module and 0 average violations; all 12
interrogate floors pass) and found one real defect: the xenon block ceiling
was still 145 with a comment claiming present-tense parity with the ledger,
while two banked improvements (`LocalRsiLoop._fitness_decision`,
`LocalRsiLoop.export_promotions`) had already pulled the ledger down to 143 —
the exact silent divergence the step's own comment warns is "a signal that one
of them stopped looking".

`tests/test_complexity_gate_scope.py` is new (+5 tests in `tests/`), pinning
the widened state structurally instead of by re-running the scanners:

1. radon `DEFAULT_SCAN` covers every shipped `packages/*/src` root discovered
   from the tree, with the `third_party` exclusion — a tenth package added
   without widening the gate fails here.
2. the xenon step scans exactly the same root set, also excluding
   `third_party`.
3. `XENON_BASELINE` equals the radon ledger's length, so an improvement must
   lower both in the same PR (the ceiling now reads 143).
4. the xenon step still enforces all three axes — block count, module rank
   (identity ledger, both `comm` directions), and a project average that
   fails above 0 — the two axes the pre-#1682 step computed and threw away.
5. every shipped package sits under an interrogate floor (core via its four
   per-path floors, the other eight via their own).

No existing tests were removed or weakened; the five are static reads of
`scripts/check-radon-baseline.py`, `quality/radon-baseline.json` and
`.github/workflows/quality.yml`, so no suite runtime is added beyond
collection.
