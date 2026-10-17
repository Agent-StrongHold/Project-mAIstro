---
inventory-delta:
  tests/: +0
---
# PR #1341 — Exit 1 evidence reconciliation

The existing 39 Gates Ran regression tests are the behavioral evidence named by
ADR-091226-1341 and SPEC-091226-1341. A module-level
`pytest.mark.contract("behavioral")` makes that evidence discoverable by the
contract-marker ledger without duplicating tests. The ADR-index fixture count
tracks the current corpus: 83 indexed ADR rows.
