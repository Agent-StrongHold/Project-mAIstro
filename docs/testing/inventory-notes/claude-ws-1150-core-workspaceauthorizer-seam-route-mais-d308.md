---
inventory-delta:
  packages/maistro-core/tests: +22
---
# claude-ws-1150-core-workspaceauthorizer-seam-route-mais-d308

`packages/maistro-core/tests/workspaces/test_workspace_authorizer.py` is new
(#1150). It adds 22 node IDs and removes none. Seven tests run against each of
the three Workspace store backends (memory, SQLite, PostgreSQL): member VIEW,
foreign and unknown Workspace denied the same way, two blank-principal cases,
owner-only ADMINISTER, revocation after `remove_membership`, and
`visible_workspace_ids` matching `list_for_user`. That makes 21. The 22nd is a
single test for a store that never returns a membership. The PostgreSQL leg
skips unless `MAISTRO_TEST_PG_DSN` is set.
