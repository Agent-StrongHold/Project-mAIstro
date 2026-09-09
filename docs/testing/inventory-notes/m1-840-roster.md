---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/hive-conductor/backend/tests: +21
  tests: +16
---

# #840 slices 1-3 — agent roster authority (hive-conductor + maistro-core)

Implements Slices 1-3 of the #840 design: the bridge stops rebinding
`container.agents` (+1 bridge test resolving through the real
`_wire_hierarchy` closure); every `stores.agents` writer moves behind
`services/agent_materialization.py` (+6 chat-created-agent tests pinning
dispatchability, the Warden scan verdict in provenance, deterministic
upsert ids, workspace scoping, and fail-closed refusals; +16 gate tests for
`scripts/check-agent-store-writes.py`, including an integration run over
this tree); and the demo seed is scoped to demo mode while boot
materializes the canonical manifest roster (+11 manifest/boot/seeding tests:
global-row equivalence with the canonical roster, idempotent upsert with
stale-row reap, non-dispatchable stamping without a bridge, the fail-closed
no-roster contract, demo/PM-POC no-ops, and demo-mode-only seeding; +3
dispatch-invariant tests proving workspace-first precedence, spawn-name
resolution, and capability refusals hold with manifest rows in the store).
`packages/maistro-core/tests` is unchanged: Slice 1 fixes the conductor-side
adapter, not the factory contract.
