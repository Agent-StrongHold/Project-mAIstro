---
lane: L1084
issue: "#1084 [M1-D2][#56] Converge shipped Hive chat and Agent model egress onto canonical Provider/Binding/Invocation"
round: "implement+repair, 2026-10-24 (SPEC-285 incremental streaming)"
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
- The 2026-10-24 repair round resolves the NEEDS-DEEP-REVIEW streaming item:
  SPEC-285 (docs/specs/) specifies the narrow on_chunk observer seam, the
  gateway pumps chunks live, stream_chunks bridges them through a queue, and
  streamed calls now record usage from the terminal usage chunk. reachability
  stays red on admission_identity — verified identical on the pre-repair head,
  still a pre-existing base condition.

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

- RESOLVED this round (SPEC-285, docs/specs/SPEC-285-model-egress-incremental-
  streaming.md): bounded work item 3's narrow callback/lifecycle design is
  specified, and the shipped path now honors it — _stream_body (llm_gateway.py)
  pumps normalized chunks to an on_chunk observer while the Invocation is
  RUNNING, stream_chunks bridges them live through a queue, and terminalization
  still happens only after full consumption (failure → FAILED/UNKNOWN,
  consumer abandonment → UNKNOWN cancel, dedup replay from the terminal
  record). Streamed calls now also record usage from the terminal usage chunk,
  which the buffered path lost entirely. Owner ratification of the streaming
  semantics is requested in the spec's ratification note; the admission owner
  decision (2026-09-23) is untouched.
