---
lane: L1084
issue: "#1084 [M1-D2][#56] Converge shipped Hive chat and Agent model egress onto canonical Provider/Binding/Invocation"
round: "implement, 2026-10-20"
head: ee063fde9 (merge of origin/develop e20e9f52 into auto-1084 @ bfba2d4b9)
---

# 1084 lane notes (read before touching this branch)

## State
- Branch = origin/develop + this issue's diff (23 files). The blocked develop
  sync was resolved as a true merge commit (eacde211a); never re-resolve it by
  hand-editing quality/*.json back toward old develop.
- Two repair commits follow: b728bca8a (census rekey after the radon refactor
  of execute_model_chat/_post_model_chat + bridge fakes), ee063fde9 (server
  chat door's conductor consumes persisted execution identities).

## Ratchet traps hit this round (do not rediscover)
- radon: new/moved blocks must stay grade B; execute_model_chat and
  GovernedModelChatClient._call were C(14) before the split. Any edit that
  pushes a block to C fails check-radon-baseline with an unbaselined key.
- vulture: deleting get_default_quota_tracker (quota/default_tracker.py) would
  demand a vulture-baseline row prune (prohibited); it is used again by
  default_effect_context's ephemeral composition — keep that call.
- wiring-reads: Container.model_chat_client must keep a direct attribute read
  in production code (hive adapters/maistro_core.py); getattr hides it.
- direct-effects census (quality/direct-effect-call-sites.json +
  scripts/check_direct_effects.py _PATH_CALLS) is keyed by qualname — renaming
  llm_gateway functions means rekeying both, dispositions unchanged.
- suite inventory: note is docs/testing/inventory-notes/1084-model-egress-
  convergence.md (core +4, server +1, hive +2 vs develop).
- reachability is RED on pure origin/develop too
  (maistro.runs.admission_identity, the inactive #1851 leaf; see its module
  docstring). Not ours; fixing it needs a reachability-baseline entry — a
  ledger edit outside this lane.

## Open design item for the owner
- Bounded work item 3 (incremental streaming through the governed lifecycle)
  shipped as Invocation-truthful buffering: _stream_body (llm_gateway.py:299)
  buffers, GovernedModelChatClient.stream_chunks (model_chat.py:734) replays.
  The shipped /chat/stream route already emitted a single done frame (M0
  decision, routes/chat.py:233), so no shipped consumer lost incremental
  tokens — but the narrow callback/lifecycle design the issue asked to specify
  before implementation was not written as an ADR. Needs owner review.
