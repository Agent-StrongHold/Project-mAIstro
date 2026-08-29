---
inventory-delta:
  packages/maistro-core/tests: +76
---
# claude-issue-516-durable-workspace-store-5ae0

Two new files, both under `packages/maistro-core/tests/workspaces/`. Nothing was
moved, renamed, split or deleted, so the number is not hiding a compensating
change, and the two suites already in that directory
(`test_store.py`, `test_membership.py`) are untouched — they still cover the
in-memory reference's own behaviour and still pass unchanged.

`test_workspace_store_conformance.py` is the bulk of it. Nineteen bodies
parametrised over three backends — the in-memory reference, SQLite and
PostgreSQL — plus a five-way parametrise over the membership accessors that
must raise `WorkspaceNotFound`. The in-memory leg is deliberately inside this
suite rather than beside it: it is the definition of the contract, so running
it here is what makes "the durable stores behave like the reference" a
comparison rather than a claim.

`test_wiring.py` covers the backend selection, including the unmigrated-pool
fallback, which must warn rather than silently hand back in-memory Workspaces.

**Counted with a PostgreSQL server absent, which is how the inventory job runs.**
The PostgreSQL legs are collected either way — `pytest.skip` happens at run
time, not collection time — so the node-id count is the same with and without a
server, and this number does not move when the `postgres` job runs the same
files with `MAISTRO_REQUIRE_PG_LEGS=1`.

## Revised after Codex review (+2, 69 total)

Two node IDs added in `tests/workspaces/test_wiring.py`, and the existing
tests there rewritten rather than extended -- because they were asserting the
defect.

Every test in that file paired an `InMemoryProjectScopeStore` with a SQLite or
PostgreSQL Workspace store and asserted the result was correct. That pairing
*is* the split #516's acceptance criteria forbid -- "so a deployment cannot end
up with its Workspaces in one database and their Root Projects in another" --
and one test asserted the silent fallback by name
(`test_an_unmigrated_postgres_pool_falls_back_and_says_so`). The suite encoded
the behaviour the criterion prohibits, which is why the criterion could be
claimed as met.

Each backend is now exercised against its own Project store, and the two new
tests assert that an unhonourable pairing is *refused*: PostgreSQL Projects
with no pool, and SQLite Projects with no connection. The unmigrated-pool test
survives with its assertion inverted, from "falls back and says so" to
"is refused rather than split".

One fixture mistake worth recording, because it is the same shape as the one
in the JSONB verification. The refusal tests first used hand-written doubles
named `_PgProjectStoreDouble` and `_SqliteProjectStoreDouble`; the selector
reads the backend from the class-name prefix, and a leading underscore does not
match `Pg`. So all three refusal tests passed the selector a store it
classified as in-memory and asserted a refusal that could never come -- they
failed with DID NOT RAISE, which is the only reason it was caught. They now use
the real `PgProjectScopeStore` and `SqliteProjectScopeStore`, which construct
without a live connection and cannot drift from what the selector sees.

## Project-tree teardown (+3, 72 total)

One conformance test, three node IDs -- one per backend, which is the entire
point of it.

`WorkspaceStore.delete` promised to purge the Workspace's Projects and reached
that purge through `getattr(self.project_store, "purge_workspace", None)`. Only
`InMemoryProjectScopeStore` defined the method, so on PostgreSQL and SQLite the
branch evaluated to `None` and did nothing: the Project tree, its memberships
and its scoped resources survived with no Workspace left to reach them by.

The old delete test asserted the Workspace row and its memberships were gone
and stopped there, so it passed on all three backends while two of them
orphaned everything below. `test_delete_purges_the_whole_project_tree_it_owns`
builds a *nested* child under the Root Project, gives it a membership and a
scoped resource, deletes the Workspace, reopens, and asserts both Projects are
unreachable.

Nested rather than root-only because both schemas declare `ON DELETE RESTRICT`
on the self-referencing parent link: a purge that deletes in the wrong order
fails on the parent instead of silently under-deleting, and one level of depth
is enough to tell a correct implementation from either failure.

Verified against the pre-fix code, which is the only reason to trust it:
restoring the duck-typed call fails `[sqlite]` and `[postgres]` with the child
Project still present, and passes `[memory]`. That split is the defect in one
line -- the only backend that worked was the only one the old test could
distinguish.

## Revised again after CI's diff-coverage gate (+4, 76 total)

Two tests in `tests/projects/test_scope_store_conformance.py`, each running on
both durable backends. The gate could not see the gap until the branch had a
merge base with `develop` again; once it did, it named `purge_workspace`'s
overflow path in both stores -- `pg_scope_store.py` 87/91 and
`sqlite_scope_store.py` 130/131/135, the `ProjectIntegrityError` raise and, on
SQLite, the rollback before it.

- `test_a_tree_deeper_than_the_purge_bound_fails_rather_than_spinning` -- the
  delete runs leaf-first and repeats until a pass removes nothing, so its
  termination rests on there being no cycle, an invariant `move_project`
  enforces somewhere else entirely. If that ever breaks the request has to
  FAIL; an unbounded loop would hang it, and a hung delete is the harder
  failure to diagnose. `_MAX_PURGE_PASSES` is patched down rather than met:
  building a sixty-five-deep tree would prove something about the number
  sixty-five, not about the branch.
- `test_a_tree_within_the_bound_is_purged_whole` -- the loop's normal exit and
  what it leaves behind, so the pair covers both ways out of it.

The second test first asserted `pytest.raises(ProjectNotFound)` on the purged
descendant and failed. `get` answers absence with `None`; the assertion was
wrong, not the store. It now asks the question directly, of the deepest
descendant and of the Root.
