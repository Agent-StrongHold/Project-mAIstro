---
inventory-delta:
  tests/: +5
---
# 1682-complexity-gate-scope

Issue #1682 widened the complexity gates (radon ratchet, xenon, interrogate)
from `packages/maistro-core/src` to every shipped package's `src/`, with the
grants and the per-identity ledger landing through #1683/#1684/#1793. Two
defects survived that landing, both found by re-measuring rather than trusting
the comments:

1. **The xenon ceiling drifted from the ledger it mirrors.** The widening
   landed with `XENON_BASELINE` at 145 and a comment claiming present-tense
   parity with check-radon-baseline.py's ledger, while banked improvements
   (`LocalRsiLoop._fitness_decision`, `LocalRsiLoop.export_promotions`, then
   the post-2026-10-04 Boy Scout waves) pulled the ledger down to 137 — the
   exact silent divergence the step's own comment warns is "a signal that one
   of them stopped looking", and the reason the pin test below failed on the
   pre-repair head.
2. **The shipped SDK was the tenth tree, and only xenon watched it.** The
   widening batch keyed its grants and floors to nine `src/` roots;
   `packages/maistro-ext-sdk/src` stayed in xenon's scan but out of the radon
   scan and the interrogate floors, so the two instruments disagreed by
   exactly the SDK's two C blocks (`manifest.py::_validate_least_authority`
   C(14), `ranges.py::VersionRange.satisfied_by` C(12)).

This change closes both: the radon scan adds `packages/maistro-ext-sdk/src`
(`packages/maistro-ext-harness` stays out by name — stdlib-only CI tooling, not
shipped product source), banks the two SDK blocks at their measured complexity,
re-pins the ceiling at 139 (137 + 2, re-measured: xenon reports 139 block
identities one-for-one with the ledger, 0 module and 0 average violations), and
floors the SDK's docstrings at their measured 73%. The two new ledger
identities carry grants in `quality/ratchet-authorizations.json`; per the
two-merge rule the grants must be on the trusted base before this branch's
radon ratchet passes, so this branch is blocked on its own grants landing
first — the gate says so itself ("Land a grant keyed as
'<qualified-block>@<new-complexity>' first"), and the grants are inert here
because the authorizations are read from the base revision, never the
candidate.

`tests/test_complexity_gate_scope.py` is new (+5 tests in `tests/`), pinning
the widened state structurally instead of by re-running the scanners:

1. radon `DEFAULT_SCAN` covers every shipped `packages/*/src` root discovered
   from the tree (dev-only packages excluded by name), with the `third_party`
   exclusion — a new package added without widening the gate fails here.
2. the xenon step scans exactly the same root set, also excluding
   `third_party`.
3. `XENON_BASELINE` equals the radon ledger's length, so an improvement must
   lower both in the same PR (the ceiling now reads 139).
4. the xenon step still enforces all three axes — block count, module rank
   (identity ledger, both `comm` directions), and a project average that
   fails above 0 and actually raises the step's `fail` flag — the two axes
   the pre-#1682 step computed and threw away.
5. every shipped package sits under an interrogate floor (core via its four
   per-path floors, the nine others via their own), with option operands
   (`-f`, `-e`) parsed as values so an excluded path is never mistaken for
   covered ground.

No existing tests were removed or weakened; the five are static reads of
`scripts/check-radon-baseline.py`, `quality/radon-baseline.json` and
`.github/workflows/quality.yml`, so no suite runtime is added beyond
collection.
