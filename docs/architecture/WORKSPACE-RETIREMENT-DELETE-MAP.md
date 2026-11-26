# Workspace retirement delete map (#2274 / `conductor-408`)

**Status:** living map — shrink-only with `quality/workspace-retirement.json`  
**Plan:** [WORKSPACE-CUTOVER-PLAN.md](WORKSPACE-CUTOVER-PLAN.md) §5 / §9  
**Inventory:** [packages/hive-conductor/docs/route-inventory.md](../../packages/hive-conductor/docs/route-inventory.md)

This document owns **coordinated DELETE disposition** for superseded Conductor
pages. Replacement issues build surfaces; this map records which delete PR (or
ratified deferral) burns each §9 DELETE/HIDE row. Closing #2274 requires every
row below checked.

## v1.0 DELETE / HIDE rows

| Legacy page / route | Disposition | Replacement owner | Delete / hide owner | Status |
|---|---|---|---|---|
| `Dashboard.tsx` `/dashboard` | DELETE after Home ACs | #1048 | #2274 (after #1048) | deferred — Home shell in flight |
| Chat local-only (pre-#1822) | REPLACE path | #1822 | #2274 (shim retirement after #1822) | deferred — durable chat in flight |
| `Agents.tsx` `/agents` | DELETE after Capabilities | #2273 | #2274 | deferred — Capabilities shell in flight; URL-only after nav rehome |
| `MCP.tsx` `/mcp` | DELETE after Capabilities | #2273 | #2274 | deferred — same |
| `Skills.tsx` `/skills` | DELETE after Capabilities | #2273 | #2274 | deferred — already URL-only |
| `Topology.tsx` `/topology` | DELETE after Capabilities | #2273 | #2274 | deferred — same |
| `Missions.tsx` `/missions` | MERGE → Backlog then DELETE | #82 | #2274 | deferred — Backlog ships; Missions still linked |
| `WorkItems.tsx` `/work-items` | MERGE → Backlog then DELETE | #82 | #2274 | deferred — already URL-only |
| `Memory.tsx` `/memory` | DELETE after user/Workspace memory | #776 / #1047 | #2274 | deferred |
| `KnowledgeBase.tsx` `/knowledge` | DELETE after memory surface | #776 / #1047 | #2274 | deferred — still in nav |
| `Evolution.tsx` `/evolution` | **HIDE v1.0** (restore v1.2) | #51 (Evolve impl) | #2275 | in flight — hide PR |
| `OptimizationInbox.tsx` `/optimizer` | MERGE → Attention | #1049 | #2274 | deferred — Attention shell in flight |
| `MessageBoard.tsx` `/messages` | MERGE → Attention | #1049 | #2274 | deferred |

## Rules

1. **No delete before replacement ACs.** Coordinated with the replacement owner.
2. **Shrink-only ledger.** Removing an importer or marking `deleted: true` must
   match the tree; new importers of retiring modules fail CI.
3. **No permanent redirect facades** that revive deleted modules (`AC-5`).
4. **Hide ≠ delete.** Evolution is HIDE (#2275); file may remain for v1.2 restore.

## First safe deletes (when unblocked)

When #2273 Capabilities ACs land and e2e covers the primary surface:

1. Unregister `/agents`, `/mcp`, `/skills`, `/topology` from `App.tsx`
2. Prune retirement ledger importers → empty → later `deleted: true` + file removal
3. Update `route-inventory.md` + navigation-coverage in the same PR

When #2275 merges: Evolution row moves to **done (HIDE)**.
