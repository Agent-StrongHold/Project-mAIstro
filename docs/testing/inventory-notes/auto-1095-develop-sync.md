---
inventory-delta:
  tests/: -19
---

# auto-1095-develop-sync

Resolving the preserved develop-sync conflict on `auto-1095` moved two test
files out of the root tree without losing their content:

- `tests/api/test_auth.py` and `tests/api/test_startup.py` were deleted by
  the `origin/develop` side (its consolidation relocated them to
  `packages/maistro-server/tests/api/`), while the #1095 branch had updated
  the root copies. The two files were byte-identical to their
  `packages/maistro-server/tests/api/` counterparts at the branch head, and
  those package-level counterparts merged cleanly carrying every #1095 test,
  so the resolution accepts the deletion: `tests/` loses the mirrored node
  IDs (net -19 after the deltas already recorded on both merged sides), and
  `packages/maistro-server/tests` is unchanged (584, verified by the gate).
- `alembic/versions/036_legacy_principal_ownership.py` is renumbered to
  `064_legacy_principal_ownership.py` (revision `064`, `down_revision =
  "063"`): develop's integrated history already assigned the `036`
  identities, the drafted sibling placement forked the chain into two heads
  (`036` and `063`), and per the integration rule recorded on
  `063_canonical_goals` a new revision appends after the integrated head
  under an unused id. No test count moves: the live suite
  (`tests/migrations/test_legacy_principal_ownership_live.py`, 3 tests) and
  the contract suite (`tests/test_legacy_principal_migration.py`) keep their
  collections and now assert the `063 -> 064` lineage.
- `tests/migrations/test_revision_metadata.py` keeps its tuple
  `down_revision` parsing (still correct for any future merge revision);
  its comment no longer cites the retired `036` shape. No count change.

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->
