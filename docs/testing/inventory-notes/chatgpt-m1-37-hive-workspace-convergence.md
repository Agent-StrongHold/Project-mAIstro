---
inventory-delta:
  packages/maistro-core/tests: +4
  packages/hive-conductor/backend/tests: +3
---

# M1 #37 — Hive Workspace convergence

Seven new tests cover the authority transition rather than adding a parallel Workspace implementation.

The maistro-core tests prove the canonical `WorkspaceStore.create()` convergence seam can retain an existing Workspace ID while provisioning the Root Project under that exact same identity, ordinary creation continues to mint distinct canonical IDs, and the exact-ID contract holds on both SQLite and PostgreSQL durable stores.

The Hive tests prove that a legacy Hive Workspace imports without ID remapping, that subsequent mutations of the legacy membership record cannot change live authorization, and that newly created Workspaces write canonical identity/membership plus a Hive-only presentation projection rather than a second Hive Workspace authority.
