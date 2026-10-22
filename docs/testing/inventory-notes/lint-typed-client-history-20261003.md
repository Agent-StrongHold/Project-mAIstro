---
inventory-delta:
  tests/: +1
---

# Restore trusted history for the frontend typed-client ratchet

PR #1814 (`082dadb8`) added `check-frontend-typed-client.py` to CI's
`lint-and-type-check` job, which still checked out only the candidate at depth 1.
PR #1847's job 111125160616 consequently failed to resolve `origin/develop`
after Ruff, mypy, and the preceding frontend checks passed.

The checkout now fetches full history so the existing provenance adapter can
resolve each event's trusted base and its ancestry. No base override, ratchet
ledger, grant, gate, or event selection changes.

One root-suite workflow contract test is added. It locates the actual ratchet
step and requires its preceding checkout to supply the complete event candidate
and full history in the workspace. It fails against the original shallow
workflow and passes after the correction. Existing frontend-debt tests and
event-aware provenance behavior remain covered.

Measured with `check-suite-inventory.py --suite tests/ --update --note
lint-typed-client-history-20261003`: 4,418 -> 4,419 root node IDs (+1).
