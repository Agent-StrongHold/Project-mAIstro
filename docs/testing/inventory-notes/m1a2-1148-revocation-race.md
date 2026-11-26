---
inventory-delta:
  packages/maistro-core/tests: +4
  packages/maistro-server/tests: +1
---
# m1a2-1148-revocation-race

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

The delegated membership POST used to read the target row with
`memberships_for` and merge it in Python before writing through
`set_membership`; an owner revocation committing between the read and the
write was overwritten by the upsert, resurrecting the revoked principal with
the stale grants (#1148, M1-A2 review evidence). The repair adds an atomic
`merge_membership` to the `ProjectScopeStore` protocol (in-memory, SQLite,
PostgreSQL) and routes the non-owner path through it.

Tests added because the race and the new primitive were otherwise unproven:

- `test_a_revocation_racing_a_delegated_merge_cannot_resurrect_revoked_grants`
  (conformance, all backends): gathers `remove_membership` against
  `merge_membership` and pins the only two valid outcomes — row gone, or row
  carrying only the delegated grant; never the resurrected union.
- `test_a_delegated_merge_preserves_the_row_it_finds` (conformance, all
  backends): the merge unions grants/delegable authority, carries
  identity/`created_at`/`denies`/`role` forward, and starts a fresh row when
  none exists.
- `test_owner_revocation_racing_a_delegated_regrant_cannot_resurrect_the_revoked_principal`
  (API): forces the exact interleaving from the review evidence (revocation
  commits before the merge decides) and fails against the old
  read-then-write handler shape.
