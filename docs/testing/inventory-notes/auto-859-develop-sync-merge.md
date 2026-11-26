---
inventory-delta:
  packages/maistro-turing/tests: +2
  packages/maistro-turing/backend/tests: +1
---

# auto-859 develop sync merge — #859 scoped cognitive state reconciled with develop #2218

This branch (issue #859: scope Turing self-model/chat state to canonical
Workspace principals and enforce bounded state writes) synced origin/develop,
which had independently landed a parallel implementation of the same epic
(#2218). The merge resolution keeps one coherent implementation and unifies
both sides' test evidence. Net test delta over the merged expectation:

- `packages/maistro-turing/tests` +2:
  `test_bridge.py::TestTuringMemoryBridge::test_store_episode_carries_principal_provenance`
  (scoped `store_episode` persists the caller's user/project provenance; the
  unscoped path stays blank) and
  `test_retrieve_episodes_scopes_reads_to_the_calling_principal` (scoped
  retrieval passes the caller's identity to the episodic store's scope filter).
  Together they pin the "state reads and writes preserve exact actor/Workspace
  provenance" acceptance criterion on the durable episodic seam, which
  previously persisted every chat capture with blank scope fields.
- `packages/maistro-turing/backend/tests` +1:
  `test_scope_isolation.py::TestDeterministicWorkspaceResolution::`
  `test_the_same_principal_resolves_the_same_scope_in_every_process` — two
  independently composed execution planes (replica stand-ins) resolve the SAME
  canonical Workspace id for one principal (deterministic uuid5 derivation),
  so a shared `SelfModelStateStore` converges instead of forking per process.

Merge-resolution notes (behavior carried from the branch, review fixes
absorbed from develop):

- `backend/state.py`: branch architecture retained (pluggable
  `SelfModelStateStore` seam, `TURING_REPLICA_COUNT` guard, bounded
  `ProducerArtifact` feed, 128-char session-id validation, LookupError on
  scope-less access); develop's review fixes absorbed: chat-session capacity
  and LRU are enforced per-Workspace partition (one scope's flood can no
  longer evict another scope's live session) and both `set_mood`/`set_facet`
  validate the candidate before any state is materialized (a rejected write
  persists nothing and installs no default scope).
- `backend/routes/`: branch's Workspace-scoped routes retained (responses name
  the canonical Workspace the state was read from / written to), plus the chat
  session factory now binds the caller's resolved scope so episodic captures
  carry user/project provenance.
- `backend/execution.py`: `scope_for` derives the canonical Workspace id
  deterministically per principal.
- `backend/tests/test_state_scoping.py` (develop's file) adapted to the merged
  API with identical intent: seam validation, no-fallback refusal, rejected
  writes install nothing, per-scope bounded registry (keying, capacity,
  cross-scope eviction immunity, LRU tie order, idle expiry, id validation).
