---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---

The DAG Workspace-selection tests now seed and authorize through the canonical
WorkspaceStore, including an explicit regression proving a stale legacy
`stores.workspaces` roster cannot authorize a DAG selection. WebSocket coverage
also exercises the production route against canonical membership, while the
legacy product record remains a presentation/recovery fixture only.
