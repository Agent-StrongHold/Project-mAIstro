---
inventory-delta:
  packages/maistro-core/tests: +12
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
