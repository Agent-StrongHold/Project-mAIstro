---
inventory-delta:
  packages/maistro-core/tests: +3
---

# #453: an authorized same-user agent read is not a cross-agent share

The master-initiative control plane (#453, 2026-09-03 Workspace product
reconciliation) requires ADR-080/SPEC-242 to clarify that "cross-agent sharing
to another principal" is not conflated with "an authorized Workspace Agent
reading canonical user-scope memory for the same user". The production
`can_read` in `maistro/memory/episodic/sharing.py` already distinguishes the
two through the principal's canonical `user_id` (the `_is_own_memory`
exact-scope branch); the docs now say so, and three new cases in
`test_sharing.py` pin the reachable behavior:

1. An authorized same-user Workspace Agent (`scope=USER`, the user's
   `user_id`, a distinct `agent_id`) reads that user's USER-scope memory
   through the own-scope branch with no `shared` marker, and the read grants
   nothing — the memory stays unshared for every other principal.
2. A different user's agent is a different principal at the same scope: denied
   while unshared, admitted once explicitly shared.
3. The agent boundary is real between two agents of the same user: the user's
   Workspace Agent is still another principal relative to another agent's
   AGENT-scope memory, so the read is denied until the owner marks the memory
   shareable.

Docs touched: ADR-080 part (C) ("One boundary, not two" paragraph) and
SPEC-242 (new "Clarification: an authorized same-user agent read is not a
cross-agent share" section, cross-referencing ADR-092526-4391's same-user
promotion amendment). No production code changed: the tests document existing
behavior so a future refactor of `_is_own_memory` cannot silently conflate the
same-user agent read with a cross-principal share.
