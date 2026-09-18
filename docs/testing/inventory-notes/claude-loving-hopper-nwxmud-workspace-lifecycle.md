---
inventory-delta:
  packages/maistro-core/tests: +9
---
# Workspace and Root Project lifecycle is crash-consistent (#1121)

Nine new collected cases in `packages/maistro-core/tests`: three tests, each
run against the memory, SQLite and PostgreSQL legs of
`tests/workspaces/test_workspace_store_conformance.py`.

- `TestAFailureMidDeleteLeavesTheWorkspaceWhole` (+9): a failure injected at
  the workspace-row delete, and one injected during the project purge, each
  leave a fresh store seeing the workspace, its owner membership and its Root
  Project intact; and after every injection, every workspace `list_for_user`
  returns still answers `root_for_workspace`. The existing create-path test
  now injects at the durable stores' `create_root_in` seam (after the
  workspace and membership rows, before the root) and also asserts the
  membership is gone and the root is absent.
