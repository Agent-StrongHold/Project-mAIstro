---
inventory-delta:
  packages/maistro-core/tests: +15
---
# #1121 review: lifecycle refusals, races, and pre-journal writers

Five conformance cases in `workspaces/test_workspace_store_conformance.py`,
each over memory (skipped: no durable boundary) / SQLite / PostgreSQL:

- a purge the schema refuses (Run history under `ON DELETE RESTRICT`) restores
  the Workspace to `active` and raises `WorkspaceRetainsHistory`, on the
  request path and on the recovery path alike;
- a create rollback over a pre-existing (imported) Project tree removes only
  the Workspace row, never the tree;
- recovery that read `creating` after the creator's compensator won neither
  resurrects the Workspace nor leaves an orphan Root;
- a creator whose row another replica's recovery activated first steps aside
  instead of purging the Root it was given;
- a Workspace row an older writer inserted without a journal row becomes
  visible after recovery.
