---
inventory-delta:
  packages/maistro-rsi/tests: +4
---

# #880: snapshot assurance scores and citations

The frozen `AssuranceCandidate` retained mutable dictionaries. A caller could
clear the supplied scores/evidence or assign through the candidate mappings,
changing eligibility, citations and ranking after the evidence was recorded.
This contradicted the harness's own immutable-evidence contract.

Two tests, each parametrized over `scores` and `evidence`, demonstrate both
aliasing and direct mutation. All four failed on the original harness
(`check-matrix-mutation-red.log` in job ad341667e2e24753b26f0486edd200d6).
Copying the mappings into read-only `MappingProxyType` snapshots fixes both
paths. Assertions check the retained values, rankability and ranking, not just
the dataclass's frozen flag. Green validation: the complete RSI suite passed
1819 tests (4 skipped), including all 26 matrix cases; suite inventory matched
1823 collected RSI nodes. Repository ruff check and format check also passed.

Only test-side comparative machinery changes; no production execution,
authorization, store, event authority, quality ledger or grant changes. The
historical baseline remains explicitly historical; the precursor Run helper's
shared-table oracle is not represented as independent production proof.
