---
inventory-delta:
  tests/: 0
---
# #358: preserve develop's 054 while resolving the audit-index collision

No new collected tests. Strengthened the existing chain-tip test to assert
revision 055 follows 054 and retains all ancestors. It fails before migration
renumbering (missing 055 / duplicate 054), then passes afterward.

Updated the live PostgreSQL audit-index round-trip test to start at and return
to 054. It additionally checks the 054 version stamp and task-admission
`generation_id` column survive the audit-index downgrade, alongside the existing
index-shape and audit-row-preservation assertions. No unrelated test removal.

The existing admission rollback test also now compares its version stamp to the
captured pre-downgrade stamp: PostgreSQL reproduced the hardcoded `054` assertion
failing after this issue advances the head to `055`. This preserves the rollback
invariant without coupling an unrelated migration to a moving chain tip.

Commands and outcomes: `docs/testing/358-5b915-repair.md`.
