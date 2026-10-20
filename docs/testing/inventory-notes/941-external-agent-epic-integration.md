---
inventory-delta:
  packages/maistro-core/tests: +2
---
# 941-external-agent-epic-integration

Epic M9-D (#941) composition proof: **discovery and invocation compose without
core source modification**. The three children landed separately — #958
(`maistro.a2a.external`), #959 (governed delegation/`DelegationContext`),
#960 (`maistro.a2a.normalize`) — and each half was tested in isolation, but
nothing demonstrated the epic's first acceptance criterion end to end: an
external Agent discovered through the registry and then *invoked as that
discovered agent* through the canonical delegation seam, using only exported
surfaces.

**+2 `packages/maistro-core/tests/a2a/test_external_agent_epic_integration.py`**

- *discovered → eligible → invoked, end to end*: an operator policy (written
  out-of-core against the `ProjectionPolicy` protocol) ingests an A2A-style
  card into `ExternalAgentRegistry`; the projection is asserted clamped
  (`t9`/`P5`/`delegation_mode="none"`/no sub-agents/`scope="external"`,
  authorized tool subset only) with remote provenance retained; eligibility
  arrives only from a reported availability probe; the peer is registered in
  `GuestPeerManager` *from the projection's own endpoint*; the dispatch goes
  through `AgentDelegateRemoteNode` under an authorized `agent_delegation`
  Binding against a real external-style poll-driven A2A peer (its own state
  engine and wire protocol over httpx); progress re-parks without minting a
  second Attempt; the terminal answer settles the same child NodeRun, and the
  card's remote version survives into the terminal Attempt evidence
  (`remote_agent_version`, `a2a_peer_url`, `peer_name`).
- *authority stays attenuated across both halves*: a descriptor refresh that
  broadens the declared surface is refused without policy approval
  (`AuthorityEscalationRefused`) and the effective projection does not move;
  a dispatch claiming a scope beyond the operator's peer ceiling is rejected
  before any bytes reach the peer (`creates == 0`) and files no child Run.

Fail-before evidence: mutating `ExternalAgentRegistry._project_card` to render
all declared tools instead of the authorized subset makes both tests fail
(the clamp and the attenuation assertions bind); the mutation was reverted
before commit.

Validation on this head: `pytest packages/maistro-core/tests/a2a` 272 passed
(270 pre-existing + 2); the delegation graph-node suites (109) re-run green;
`ruff check`/`format --check` clean on touched trees.
