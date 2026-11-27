---
inventory-delta:
  packages/maistro-core/tests: +15
  packages/hive-conductor/backend/tests: +2
---

# #37: initial roster belongs to canonical creation

Follow-up to the preserved `a4acfa8424` implementation. A real first-import
race remained: Hive committed canonical identity/owner/Root, then replayed the
legacy roster through separate membership writes. A second client's revocation
between those operations was overwritten. The process-local migration lock
could not fence the other database client.

`WorkspaceStore.create(initial_memberships=...)` now validates the entire roster
before writing and commits it with identity and Root in the existing canonical
transaction. The creator remains an owner. Fresh Hive imports do not upsert
members after that commit. Durable interrupted imports remain quarantined;
only ephemeral development recovery resumes its roster copy. No new Workspace
store, authorization path, scheduler, or execution model is introduced.

Tests:

- `TestInitialRosterIsPartOfCreation` adds 15 cases across memory/SQLite/PG:
  complete roster and Root visible after create, invalid user/role/creator
  demotion writes nothing, and Root failure rolls back every initial member.
- `test_first_import_cannot_replay_a_revocation_after_canonical_create` adds
  SQLite/PG production-bridge tests. A deterministic hook pauses the first
  import immediately after canonical create, revokes Bob through an independent
  connection/pool, then resumes migration. Bob remains revoked across two
  restarts; the roster was already complete at create's return.

Regression proof executed before production edits: the SQLite import test failed
at `assert not await workspace_authority.is_member("bob", workspace_id)` with
`assert not True`. It reproduced the actual resurrection rather than assuming
that a green store test proved the import path safe.

Validation results and remaining issue-wide acceptance gaps are recorded in
`37-atomic-import-validation.md` alongside this note.
