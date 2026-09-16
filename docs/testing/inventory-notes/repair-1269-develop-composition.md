---
inventory-delta:
  formal/: +0
  packages/maistro-core/tests: +9
  tests/: -8
---

The develop merge carried the org-bound-global memory visibility rule from #1258,
while the formal isolation property still constructed GLOBAL memories without
passing the generated organization context. The property now exercises the same
organization-bound contract as `matches_scope`, preserving the security behavior
and preventing a false composition failure.

The suite-count deltas are inherited composition fallout, not new tests in this
repair: develop contributes nine collected `maistro-core` test nodes and removes
eight root-test nodes. They are recorded here so the inventory gate measures the
composed tree rather than treating those already-landed changes as silent drift.
