---
inventory-delta:
  packages/maistro-core/tests: +2
  packages/maistro-server/tests: +1
---
# #66 Agent security boundaries

The Agent owns the invariant content-security pipeline at the product boundary.
Session history is injected before the input gate, and each user turn is
scanned together with the bounded ordered prefix of prior messages
(`prior_message_context`), so an instruction split across individually-benign
turns arrives at the Warden as one analysis context instead of as trusted
fragments. Prior untrusted turns carry an explicit `untrusted` provenance
label; trusted system/developer turns are never concatenated into
attacker-controlled analysis text. Final assistant content crosses the
Agent-owned Warden+PII boundary (`_prepare_final_output`) outside every
strategy, and a delegated agent's response is re-sanitized on return. Missing
auth is the role-less anonymous principal, never a bypass of the protected
path.

The server's roster-floor fallback (`ConductorAgent`) wires the Container's
Warden and Sentinel and runs its final answer through
`Sentinel.process_output` before returning; its single test proves the
anonymous principal reaches that output boundary. Inbound scanning on this
path stays the Conduit gate's job: a second scan here would rescan the
projected-memory context block the gate deliberately treats as context, not
input (#776).

Note: this lane's changes were re-applied onto a develop trunk that had
already landed a superset of the aggregate/centralization work (#2242 M2-A
trust pipeline); the merge keeps the trunk implementation and this lane's
multi-turn-context and anonymous-principal tests, adapted to it.
