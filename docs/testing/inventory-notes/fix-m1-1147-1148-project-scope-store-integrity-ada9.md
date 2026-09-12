---
inventory-delta:
  packages/maistro-core/tests: +14
  packages/maistro-server/tests: +1
---
# fix-m1-1147-1148-project-scope-store-integrity-ada9

Ten new tests in `test_scope_store_conformance.py` for #1147/#1148, run against
both durable backends the file already parametrizes over (SQLite, PostgreSQL):

- Repeated `set_membership` grants update the one canonical row in place.
- A revoked membership is gone and can be re-granted.
- Concurrent `set_membership` writes for one principal leave exactly one row
  (two real connections/pool acquisitions, not a single-process lock).
- A membership survives a fresh store instance, and survives removal.
- Concurrent opposite `move_project` calls cannot both commit a cycle — exactly
  one is refused, and `lineage()` stays acyclic for both.

Two more in `test_scope.py`, covering the same API surface on the in-memory
reference store (not parametrized by the conformance file above by design —
see that file's own docstring):

- `remove_membership` revokes a grant and is idempotent when none exists.
- Deleting a Workspace purges its memberships via `purge_workspace` (the fix
  to a pre-existing loop-variable bug that iterated dict keys as if they were
  bare membership ids), leaving an unrelated Workspace's memberships intact.

No tests removed or renamed; the delta is additive, matching the new
`remove_membership` API and the SQLite write-serialization fix in this PR.

Three more, added closing gaps a PR review surfaced:

- `test_scope_store_conformance.py`: a pre-#1148 SQLite database (the old
  `membership_id`-only primary key, with a real duplicate row for one
  `(project, principal)`) upgrades its `canonical_project_memberships` table
  in place via `ensure_schema()`'s new migration step, keeping the
  most-recently-created row and accepting writes afterward.
- `test_scope_store_conformance.py`: an unlocked SQLite writer (`create`)
  cannot collide with a locked one (`move_project`) opening `BEGIN
  IMMEDIATE` while the unlocked writer's implicit transaction is still
  open — forces the exact interleaving deterministically (a monkeypatched
  `commit()` pauses `create()` mid-transaction) rather than hoping the
  event loop reproduces it; fails with `OperationalError: cannot start a
  transaction within a transaction` against the pre-fix code, confirmed by
  running it against `git show HEAD:...sqlite_scope_store.py` directly.
- `packages/maistro-server/tests/api/test_projects_api.py`: a non-owner's
  delegated re-grant (via `add_project_membership`) cannot silently clear
  an existing owner-issued deny just because its request omits `denies` —
  `set_membership`'s upsert-in-place semantics (#1148) would otherwise let
  a grant-only request launder away a deny nothing else in the request
  touched.
