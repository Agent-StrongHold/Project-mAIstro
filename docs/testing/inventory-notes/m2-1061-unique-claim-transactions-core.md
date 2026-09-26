---
inventory-delta:
  packages/maistro-core/tests: +15
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

## Reconciliation repair (2026-09-24): no false alarm for seam-created accounts

Evidence-driven follow-up: accounts created through `put_raw_with_unique_claims`
have no `unique_fields` row (the seam writes `kv_store` only; the
`unique_fields` claim would appear only at the first password rehash), so
`_warn_about_unclaimed_duplicate_usernames` — written for #1528's legacy
duplicates — flagged every legitimately created account on every restart,
telling operators a healthy hive held an ambiguous duplicate and should
"resolve manually". The warning now also treats an ACTIVE canonical
`username_claims` record naming the exact row as a durable uniqueness claim;
quarantined, corrupt, crossed (foreign `user_id`), and genuinely unclaimed
rows stay loud.

**+3 `packages/maistro-core/tests/state/test_persisted_store.py`** pin the
suppression semantics: a seam-created account warns nowhere; a duplicated
pair warns for exactly the row holding neither layer's claim (order-independent
assertion computed from the backfilled `unique_fields` holder); a quarantined
or crossed claim never silences its row. The pre-existing legacy-duplicate and
repeated-initialize tests still pass unchanged.
