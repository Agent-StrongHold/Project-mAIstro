---
inventory-delta:
  packages/maistro-core/tests: +4
  packages/hive-conductor/backend/tests: +7
---

# M1 #37 — Hive Workspace convergence

Eleven new tests cover the authority transition rather than adding a parallel Workspace implementation.

The maistro-core tests prove the canonical `WorkspaceStore.create()` convergence seam can retain an existing Workspace ID while provisioning the Root Project under that exact same identity, ordinary creation continues to mint distinct canonical IDs, and the exact-ID plus chronology contract holds on both SQLite and PostgreSQL durable stores.

The Hive tests prove exact legacy ID/Root Project/timestamp preservation; legacy membership mutations cannot change live authorization; fallback-created Workspaces retain restart recovery evidence; interrupted roster imports resume; malformed ownerless rows are quarantined without blocking valid Workspaces; durable source retirement does not fire the materialized-agent deletion cascade; and pre-existing canonical membership wins over stale legacy membership.

Existing route/program tests were also migrated to await and mutate the canonical Workspace authorization seam; those are corrected existing nodes, not inventory additions.
