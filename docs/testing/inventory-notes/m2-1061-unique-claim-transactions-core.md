---
inventory-delta:
  packages/maistro-core/tests: +12
---

# M2 #1061 — atomic username-claim transactions (core seam)

**+12 `packages/maistro-core/tests/state/test_unique_claim_transactions.py`** —
the storage contract behind canonical username allocation, defined directly
against `PersistedStore` rather than only through hive-conductor's registry:

- `put_raw_with_unique_claims`: claims and records land together; a lost
  claim race refuses and writes no record; a failed record insert rolls the
  claim back; an unrun writer times out; empty inputs are refused.
- `delete_raw_with_unique_claims` (setup rollback primitive): removes a
  matching pair; refuses a claim owned by another account, a missing claim, a
  corrupt (unparseable) claim, and a record that no longer matches — every
  refusal leaves the surviving side untouched; timeout and empty-input
  refusals included.

These tests exist because the hive suite exercises the two transactions under
`--source=packages/hive-conductor/backend`, so the
`packages/maistro-core/src/maistro/state.py` lines the diff gate scores were
recorded as unmeasured in the combined CI report even though behavior was
covered end-to-end. The contract now has first-party coverage in the package
that owns the code.
