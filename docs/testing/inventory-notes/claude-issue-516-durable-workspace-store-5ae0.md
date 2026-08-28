---
inventory-delta:
  packages/maistro-core/tests: +67
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
