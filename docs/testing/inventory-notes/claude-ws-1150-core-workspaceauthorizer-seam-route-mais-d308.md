---
inventory-delta:
  packages/maistro-core/tests: +24
---
# claude-ws-1150-core-workspaceauthorizer-seam-route-mais-d308

`packages/maistro-core/tests/workspaces/test_workspace_authorizer.py` is new
(#1150). It adds 24 node IDs and removes none.

- Seven tests run against each of the three Workspace store backends (memory,
  SQLite, PostgreSQL), for 21 IDs: member VIEW, foreign and unknown Workspace
  denied the same way, two blank-principal cases, owner-only ADMINISTER,
  revocation after `remove_membership`, and no exception chain on a denial.
- Three tests run once each on the in-memory store: a store that never returns
  a membership, string or unknown actions, and a non-string principal.

The PostgreSQL leg skips unless `MAISTRO_TEST_PG_DSN` is set.
