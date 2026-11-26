---
inventory-delta:
  packages/maistro-turing/backend/tests: +21
  packages/maistro-turing/tests: +4
---

# #859 Turing cognitive state scoped to canonical Workspace principals

Branch: `auto-859`. Base: `develop@c5e070d97d07800464972ee2c026a4d525ffbb21`.

Turing's self-model snapshot was a process-global singleton (the audit
demonstrated one admin's mood PATCH changing another user's snapshot), chat
sessions lived in an unbounded process-local map keyed by client-controlled
session ids, and the documented `clamp_weight` tier safeguard was not on the
actual memory write path. This change makes Turing cognitive state a scoped
extension of the canonical Workspace model with one validated mutation seam
and explicit bounded/restart semantics. Turing stays optional domain state:
no second identity or Workspace system is introduced — scope identity is
resolved through the existing canonical execution-plane mapping
(`TuringExecutionPlane.scope_for`), now public so the state routes use the
same resolution chat admission already used.

## In bounds

- `packages/maistro-turing/backend/state.py` — workspace-scoped self-model
  store (`WorkspaceSelfModelState`, `SelfModelStateStore` contract +
  `InProcessSelfModelStateStore`), bounded workspace-owned
  `ChatSessionRegistry`, bounded published-artifact feed, replica guard
- `packages/maistro-turing/backend/config.py` — `TURING_REPLICA_COUNT`
- `packages/maistro-turing/backend/execution.py` — public `scope_for`
- `packages/maistro-turing/backend/routes/{state,admin,chat,feed}.py` —
  scoped reads/writes through the canonical scope; bounded feed payload
  rejection mapped to 400
- `packages/maistro-turing/src/maistro_turing/bridge.py` — weight clamp +
  type/tier validation at the single `store_episode` write seam
- `packages/maistro-turing/src/maistro_turing/tiers.py` — `clamp_weight`
  refuses non-finite proposals
- `packages/maistro-turing/src/maistro_turing/runtime/__init__.py` —
  bounded per-session history (`MAX_HISTORY_TURNS`)
- this note

## Out of bounds

- canonical execution internals (`Goal -> Graph -> Run -> NodeRun -> Attempt`)
- the Turing-internal service-identity model (#858) and the human session
  stub in `routes/auth.py` (login sessions are not Turing cognitive state)
- producers' drive math and the canonical Warden boundary (#1139/#1158)
- any durable-store implementation: the contract is published, the durable
  composition remains future work, and nothing claims it exists

## Test movement

- `packages/maistro-turing/tests` +4: `clamp_weight` refuses NaN/±inf
  (tiers); the memory bridge clamps out-of-range weights to tier bounds
  exactly once at `store_episode`, and refuses non-finite, non-real, and
  unknown-tier proposals without reaching the store (bridge); session
  history is trimmed to `MAX_HISTORY_TURNS` with oldest turns falling off
  (runtime).
- `packages/maistro-turing/backend/tests` +21: a new
  `test_scope_isolation.py` proving the #859 acceptance matrix —
  two-user/two-Workspace isolation over the real HTTP surface (admin mood
  and facet patches never reach the other principal's snapshot), session-id
  guessing collapsing into an isolated fresh session in the guesser's own
  scope (prompt-level evidence, admin conversation untouched), an invalid
  session id refused as 400 at the chat/registry boundary, registry
  validation/bounds (scope and session-id validation, LRU cardinality cap,
  TTL lifetime), refusal of scope-less state access (no process-global
  fallback), bounded published feed (payload bounds at the write seam and
  over HTTP, count cap), and restart/replica semantics (fresh composition
  starts from documented defaults, a multi-replica declaration refuses the
  process-local authority, replica-count validation, and a shared
  `SelfModelStateStore` composing without divergence). The former
  `test_snapshot_reflects_admin_mood_change` — which asserted the audited
  cross-user leak as correct behavior — is replaced inside `test_state.py`
  by `test_admin_mood_change_cannot_reach_another_users_snapshot` (net zero
  there; both counts below reflect the new file).
